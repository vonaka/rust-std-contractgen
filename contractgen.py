#!/usr/bin/env python3

import datetime
import os
import shutil
import subprocess
import sys
import urllib

import style

from urllib.request import urlopen

from arbiter import Arbiter
from configuration import Config
from worker import Worker


def is_annotated_already(file_to_annotate: str):
   # TODO: some functions may be annotated, while others may not.
    r = subprocess.run(["grep", "-q", "-E", "^use .*kani",
                       file_to_annotate], check=False)
    return r.returncode == 0


def is_remote(file_to_annotate: str):
    return file_to_annotate.startswith("https://") or file_to_annotate.startswith("http://")


def file_exists(file_to_annotate: str):
    try:
        if is_remote(file_to_annotate):
            urlopen(file_to_annotate).read()
            return True
        return os.path.isfile(file_to_annotate)
    except urllib.error.HTTPError:
        return False


def main():
    style.init()

    Config.init_from_arguments()
    if Config.verbose:
        Config.print()

    Config.log(f'{datetime.datetime.now()} start annotating')

    worker = Worker()
    arbiter = Arbiter()

    # make sure we can talk
    worker.hi()
    arbiter.hi()

    for f in Config.files_to_annotate:
        if not file_exists(f):
            Config.verboseprint(style.yellow(
                f'\nFile {f.removesuffix('\n')} not found. Skipping'))
            continue
        if not is_remote(f) and is_annotated_already(f):
            Config.verboseprint(style.yellow(
                f'\nFile {f.removesuffix('\n')} is already annotated. Skipping'))
            continue

        worker.set_file_to_annotate(f)
        worker.generate_contracts()
        contracts = worker.autorefine_contracts()

        grade = arbiter.assess_worker(
            Config.target_dir + worker.file_id + ".rs", contracts)
        Config.log(f'{f}: initial grade: {grade}/5')
        arbiter.log_summary()

        max_try = 3
        while max_try > 0:
            improvements = arbiter.ask_to_improve()
            if improvements == '':
                break
            worker.refine_contracts(improvements)
            contracts = worker.autorefine_contracts()
            grade = arbiter.reassess_worker(contracts)
            max_try -= 1

        Config.log(f'{f}: final grade: {grade}/5')
        Config.log(f'{f}: number of refinement rounds: {4 - max_try}')
        arbiter.log_summary()
        worker.log_summary()

        if grade < 4:
            Config.verboseprint(style.yellow(
                f'The annotation is not good enough. Skipping the rest'))
            continue
        # TODO: Save contracts with the highest grade
        worker.save_generated_contracts()

        if Config.gen_harnesses:
            harnesses = worker.generate_harnesses()
            if harnesses != '':
                grade = arbiter.assess_harnesses(harnesses)
                Config.log(f'{f}: initial grade (harnesses): {grade}/5')
                arbiter.log_summary()
                if grade < 5:
                    improvements = arbiter.ask_to_improve()
                    if improvements != '':
                        harnesses = worker.refine_harnesses(improvements)
                        grade = arbiter.reassess_worker(harnesses)
                Config.log(f'{f}: final grade (harnesses): {grade}/5')
                arbiter.log_summary()
                # Save only excellent harnesses
                if grade == 5:
                    worker.save_generated_harnesses()
            else:
                Config.log(f'{f}: no harnesses to generate')

        generated_file = Config.target_dir + worker.file_id + "_annotated.rs"
        if not is_remote(f) and Config.update_source and os.path.isfile(generated_file):
            Config.verboseprint("Replacing the original file", f)
            shutil.copyfile(generated_file, f)

            if Config.try_compile:
                ok = arbiter.try_to_compile()
                if not ok:
                    Config.verboseprint(style.yellow(
                        f'Compilation failed. Reverting the changes'))
                    Config.log(f'{f}: compilation failed')
                    # TODO: try to refine before reverting, or at least try adding contracts without proofs
                    subprocess.run(["git", "-C", Config.source_dir,
                                   "checkout", f], check=False, capture_output=True)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(1)
