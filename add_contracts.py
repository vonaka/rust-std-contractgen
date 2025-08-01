import re
import subprocess
import sys


def is_annotated_already(file_to_annotate: str):
    r = subprocess.run(["grep", "-q", "-E", "^use .*kani",
                       file_to_annotate], check=False)
    return r.returncode == 0


def trim_pub(l: str):
    if l.strip().startswith("pub(crate) "):
        l = l.split("pub(crate) ")[1].strip()
    elif l.strip().startswith("pub(super) "):
        l = l.split("pub(super) ")[1].strip()
    elif l.strip().startswith("pub "):
        l = l.split("pub ")[1].strip()
    return l


def trim_unsafe(l: str):
    if l.strip().startswith("unsafe "):
        l = l.split("unsafe ")[1].strip()
    return l


def struct_name(l: str):
    l = trim_pub(l)
    l = trim_unsafe(l)

    if l.startswith("trait "):
        n = l.split("trait ")[1].split(" ")[0]
    elif " for " in l:
        n = l.split(" for ")[1].split(" ")[0]
    elif "impl<" in l:
        n = l.split("> ")[1].split(" ")[0]
    elif "impl " in l:
        n = l.split("impl ")[1].split(" ")[0]
    else:
        return l

    return n.split("<")[0].split(":")[0]


def function_name(l: str):
    # ignore functions without bodies:
    # https://github.com/model-checking/kani/issues/3325
    if l.endswith(";\n"):
        return l

    l = trim_pub(l)

    if l.strip().startswith("const "):
        l = l.split("const ")[1].strip()

    if l.strip().startswith("unsafe "):
        l = l.split("unsafe ")[1].strip()

    if l.startswith('fn ') or (l.startswith('extern "') and '" fn ' in l):
        return l.split("(")[0].split("<")[0].split(" ")[-1]
    else:
        return l


def find_next_impl(l2, j):
    while j < len(l2):
        if not l2[j].strip():
            return j + 1
        j += 1
    return j


def intersection(l1, l2, j=0, res=[]):
    i = 0
    offset = 0
    current_impl = "_None"
    impls = [("_None", "")]
    expected_impl = ""
    use = -1
    inner = -1
    num_of_attrs = 0
    last_impl = len(l2)

    # TODO: should check for `unsafe impl` too

    while i < len(l1) and j < len(l2):

        if expected_impl == "":
            num_of_attrs = 0
            last_impl = j
            expected_impl = l2[j].strip()

            if not expected_impl.startswith("impl ") and \
               not expected_impl.startswith("impl<") and \
               not expected_impl.startswith("trait ") and \
               not expected_impl.startswith("unsafe impl"):
                expected_impl = "impl " + expected_impl
            expected_impl = struct_name(expected_impl)

            j += 1
            # Worker shouldn't add comments to its contract file but sometimes it's still doing that...
            # TODO: just in case, support multiline comments
            while j < len(l2) and (l2[j].strip().startswith('#') or l2[j].strip().startswith('//')):
                j += 1
                num_of_attrs += 1

        # Peek the impl
        (current_impl, indentation) = impls[-1]

        l = trim_pub(l1[i].strip())
        if l.startswith('impl ') or l.startswith('impl<') or \
           l.startswith('unsafe impl ') or l.startswith('trait ') or \
           l.startswith('unsafe trait ') or l.startswith('unsafe impl<'):
            try:
                current_impl = struct_name(l1[i].strip())
            except IndexError:
                i += 1
                if i >= len(l1):
                    break
                current_impl = struct_name("impl<> " + l1[i].strip())
            if l1[i].endswith('}\n'):
                current_impl = "_None"

            if current_impl != "_None":
                # Push current_impl into the stack of impls
                impls.append(
                    (current_impl, l1[i].removesuffix(l1[i].lstrip())))
            else:
                # Peek the impl
                (current_impl, indentation) = impls[-1]

            i += 1
        elif l1[i].startswith(indentation + '}'):
            # Pop the impl
            if len(impls) > 1:
                impls.pop()
            i += 1
            continue
        elif l1[i].startswith("use") and use == -1:
            use = i
            i += 1
            continue
        elif (l1[i].startswith("#![") or l1[i].startswith("#[")) and inner == -1:
            inner = i
            i += 1
            continue

        if i >= len(l1) or j >= len(l2):
            break

        fname = function_name(l1[i].strip())
        expected_fname = function_name(l2[j].strip())

        if current_impl == expected_impl and fname == expected_fname:
            tab = re.match(r"\s*", l1[i]).group()
            req = ""
            while num_of_attrs > 0:
                req += tab + l2[j - num_of_attrs].strip() + '\n'
                num_of_attrs -= 1

            res.append((i+offset, req))
            j += 1
            while j < len(l2) and not l2[j].strip():
                j += 1
            i += 1
            offset += 1
            expected_impl = ""
            last_impl = -1
        else:
            i += 1

    if use != -1 and inner > use:
        inner = -1
    return res, use, inner, last_impl


def insert_requires(original: str, requires: str, updated: str):
    with open(original, "r") as fo, open(requires, "r") as fr:
        og = fo.readlines()
        new = fr.readlines()

    no_attrs = True

    inter, use, inner, restart_from = intersection(og, new, 0, [])
    while restart_from != -1:
        for (i, l) in inter:
            no_attrs = no_attrs and l == ""
            og.insert(i, l)
        inter, _, _, new_restart_from = intersection(og, new, restart_from, [])
        if new_restart_from == restart_from:
            restart_from = find_next_impl(new, restart_from)
            if restart_from >= len(new):
                break
        else:
            restart_from = new_restart_from

    for (i, l) in inter:
        no_attrs = no_attrs and l == ""
        og.insert(i, l)

    if no_attrs:
        return
    if inner != -1 and not ("library-core-" in original) and not is_annotated_already(original):
        og.insert(inner, "#![feature(ub_checks)]\n")
    if use != -1 and not is_annotated_already(original):
        if "library-core-" in original:
            og.insert(use, """use safety::{ensures,requires};
#[cfg(kani)]
use crate::kani;
#[allow(unused_imports)]
use crate::ub_checks::*;\n\n""")
        else:
            use_str = """use safety::{ensures,requires};
#[cfg(kani)]
#[unstable(feature="kani", issue="none")]
use core::kani;
#[allow(unused_imports)]
#[unstable(feature = "ub_checks", issue = "none")]
use core::ub_checks::*;\n\n"""
            if inner != -1:
                use += 1
            else:
                use_str = "#![feature(ub_checks)]\n" + use_str
            og.insert(use, use_str)

    with open(updated, "w") as f:
        f.writelines(og)


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print(
            f'Usage: python {sys.argv[0]} <rust_file.rs> <contracts_file.rs> <output_file.rs>')
        sys.exit(1)

    rust_file = sys.argv[1]
    require_file = sys.argv[2]
    output_file = sys.argv[3]

    insert_requires(rust_file, require_file, output_file)
