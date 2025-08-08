# contractgen

#### Basic Usage

To generate preconditions for a file from the Rust standard library (e.g., `library/alloc/src/alloc.rs`), run:

`python3 contractgen.py -v -f library/alloc/src/alloc.rs`

This will generate a copy of `alloc.rs` with inserted preconditions and save it under `target/alloc_src_alloc_annotated.rs`.

By default, the file is fetched from `https://raw.githubusercontent.com/model-checking/verify-rust-std/refs/heads/main`. To use a local source directory instead, specify it with the `-s` option:

`python3 contractgen.py -v -f library/alloc/src/alloc.rs -s ~/verify-rust-std`

#### Updating the Original Source File

When using a local source directory, the original file can be automatically replaced with the annotated version using the `-u` flag. The `-k` flag ensures that the file is only updated if the generated contracts compile successfully.

#### Generating Proofs

To generate proofs for the annotated code, use the `-p` flag:

`python3 contractgen.py -v -f library/alloc/src/alloc.rs -s ~/verify-rust-std -u -k -p`

#### Configuration Files

Instead of using command-line flags, all options can be provided through a configuration file. Below is an example of a configuration file `config.conf`:
```
files_to_annotate:
    library/alloc/src/collections/linked_list.rs
    library/core/src/slice/sort/stable/quicksort.rs
    library/core/src/str/converts.rs

source_dir = ~/verify-rust-std
gen_harnesses = true
update_source = true
try_compile = true
verbose = true
worker_model = us.anthropic.claude-3-7-sonnet-20250219-v1:0
arbiter_model = us.anthropic.claude-sonnet-4-20250514-v1:0
worker_region = us-west-2
arbiter_region = us-west-2
```

Run the script with `config.conf`:

`python3 contractgen.py -c config.conf`

#### List of Options

```
options:
  -f, --files FILES    library source files to annotate
  -w, --wmodel WMODEL  llm model ID of the main worker
  -a, --amodel AMODEL  llm model ID of the arbiter
  -s, --source SOURCE  library source directory, can be local or remote
  -t, --target TARGET  the target directory of the output files
  -u, --update         update the original source files
  -p, --proof          generate harnesses
  -k, --kani           run Kani just to verify that the annotations compile without errors
  -v, --verbose        verbose mode
  -c, --config CONFIG  configuration file
```