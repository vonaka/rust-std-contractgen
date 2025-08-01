#!/usr/bin/env python3

import argparse
import configparser
import io
import logging
import pathlib
import sys

import style


class Config:
    # list of the source files functions to annotate
    files_to_annotate = []
    # bedrock model of the main worker
    worker_model = "us.anthropic.claude-3-7-sonnet-20250219-v1:0"
    # bedrock model of the arbiter
    arbiter_model = "us.anthropic.claude-sonnet-4-20250514-v1:0"
    # directory with the prompt files
    prompt_dir = "prompts/"
    # the target directory of the output files
    target_dir = "target/"
    # library source directory, can be local or remote
    source_dir = "https://raw.githubusercontent.com/model-checking/verify-rust-std/refs/heads/main/"
    # indicates whether we should update the original source files
    update_source = False
    # indicates whether we should generate harnesses
    gen_harnesses = False
    # run Kani to verify that the annotations compile without errors
    try_compile = False
    # worker region
    worker_region = "us-west-2"
    # arbiter region
    arbiter_region = "us-west-2"
    # verbose mode
    verbose = False

    logger = logging.getLogger(__name__)
    verboseprint = print if verbose else lambda *a, **k: None

    def __init__(self,
                 files_to_annotate: str = "",
                 worker_model: str = "",
                 arbiter_model: str = "",
                 prompt_dir: str = "",
                 target_dir: str = "",
                 source_dir: str = "",
                 update_source = None,
                 gen_harnesses = None,
                 try_compile = None,
                 verbose = None,
                 config_filename: str = ""):
        if config_filename != "":
            Config.init_from_file(config_filename)
        if files_to_annotate != "":
            Config.files_to_annotate = Config.parse_files_string(files_to_annotate)
        if worker_model != "":
            Config.worker_model = worker_model
        if arbiter_model != "":
            Config.arbiter_model = arbiter_model
        if prompt_dir != "":
            Config.prompt_dir = Config.normalize_dir(prompt_dir)
        if target_dir != "":
            Config.source_dir = Config.normalize_dir(target_dir)
        if source_dir != "":
            Config.source_dir = Config.normalize_dir(source_dir)
        if update_source is not None:
            Config.update_source = update_source
        if gen_harnesses is not None:
            Config.gen_harnesses = gen_harnesses
        if try_compile is not None:
            Config.try_compile = try_compile
        if verbose is not None:
            Config.verbose = verbose
        Config.files_to_annotate = Config.normalize_files(Config.files_to_annotate)
        Config.verboseprint = print if Config.verbose else lambda *a, **k: None
        logging.basicConfig(filename='logger.log', level=logging.INFO)

    def init_from_arguments():
        arg = argparse.ArgumentParser()
        arg.add_argument('-f', '--files', type=str, required=False,
                         default='',
                         help='library source files to annotate')
        arg.add_argument('-w', '--wmodel', type=str, required=False,
                         default='',
                         help='llm model ID of the main worker')
        arg.add_argument('-a', '--amodel', type=str, required=False,
                         default='',
                         help='llm model ID of the arbiter')
        arg.add_argument('-s', '--source', type=str, required=False,
                         default='',
                         help='library source directory, can be local or remote')
        arg.add_argument('-t', '--target', type=str, required=False,
                         default='',
                         help='the target directory of the output files')
        arg.add_argument('-u', '--update', action='store_true', required=False,
                         default=None,
                         help='update the original source files')
        arg.add_argument('-p', '--proof', action='store_true', required=False,
                         default=None,
                         help='generate harnesses')
        arg.add_argument('-k', '--kani', action='store_true', required=False,
                         default=None,
                         help='run Kani just to verify that the annotations compile without errors')
        arg.add_argument('-v', '--verbose', action='store_true', required=False,
                         default=None,
                         help='verbose mode')
        arg.add_argument('-c', '--config', type=str, required=False,
                         default='',
                         help='configuration file')
        args = arg.parse_args()
        Config(
            files_to_annotate = args.files,
            worker_model = args.wmodel,
            arbiter_model = args.amodel,
            source_dir = args.source,
            target_dir = args.target,
            update_source = args.update,
            gen_harnesses = args.proof,
            try_compile = args.kani,
            verbose = args.verbose,
            config_filename = args.config
        )
        Config.verboseprint = print if Config.verbose else lambda *a, **k: None


    def init_from_file(config_filename: str):
        try:
            conf = configparser.ConfigParser(allow_no_value=True)
            with open(config_filename, 'r') as file:
                conf.read_string("[config]\n" + file.read())
                if "files_to_annotate" in conf["config"]:
                    Config.files_to_annotate = Config.parse_files_string(conf["config"]["files_to_annotate"])
                if "worker_model" in conf["config"]:
                    Config.worker_model = conf["config"]["worker_model"]
                if "arbiter_model" in conf["config"]:
                    Config.arbiter_model = conf["config"]["arbiter_model"]
                if "prompt_dir" in conf["config"]:
                    Config.prompt_dir = Config.normalize_dir(conf["config"]["prompt_dir"])
                if "target_dir" in conf["config"]:
                    Config.target_dir = Config.normalize_dir(conf["config"]["target_dir"])
                if "source_dir" in conf["config"]:
                    Config.source_dir = Config.normalize_dir(conf["config"]["source_dir"])
                if "update_source" in conf["config"]:
                    Config.update_source = conf["config"]["update_source"].lower() == "true"
                if "gen_harnesses" in conf["config"]:
                    Config.gen_harnesses = conf["config"]["gen_harnesses"].lower() == "true"
                if "try_compile" in conf["config"]:
                    Config.try_compile = conf["config"]["try_compile"].lower() == "true"
                if "worker_region" in conf["config"]:
                    Config.worker_region = conf["config"]["worker_region"]
                if "arbiter_region" in conf["config"]:
                    Config.arbiter_region = conf["config"]["arbiter_region"]
                if "verbose" in conf["config"]:
                    Config.verbose = conf["config"]["verbose"].lower() == "true"
                Config.files_to_annotate = Config.normalize_files(Config.files_to_annotate)
                Config.verboseprint = print if Config.verbose else lambda *a, **k: None
        except FileNotFoundError:
            print(style.red(f'Cannot find configuration file "{config_filename}"'))
            sys.exit(1)

    def print():
        output = io.StringIO()
        print(f'Worker model: {Config.worker_model}')
        print(f'Arbiter model: {Config.arbiter_model}')
        print(f'Worker region: {Config.worker_region}')
        print(f'Arbiter region {Config.arbiter_region}')
        print('Files to annotate:')
        if len(Config.files_to_annotate) == 0:
            print('  []')
        else:
            for f in Config.files_to_annotate:
                print(f'  {f}')
        print(f'Prompt dir: {Config.prompt_dir}')
        print(f'Target dir: {Config.target_dir}')
        print(f'Source dir: {Config.source_dir}')
        print(f'Update source: {Config.update_source}')
        print(f'Generate harnesses: {Config.gen_harnesses}')
        print(f'Try to run Kani: {Config.try_compile}')
        print(f'Verbose mode: {Config.verbose}')
        out = output.getvalue()
        output.close()
        return out

    def log(msg: str):
        Config.logger.info(msg)

    def normalize_dir(dirname: str):
        if not dirname.endswith('/'):
            dirname = dirname + '/'
        if dirname.startswith('~'):
            dirname = dirname.replace('~', f'{pathlib.Path.home()}', 1)
        return dirname

    def normalize_files(fs):
        return list(filter(None, (x if x.startswith(Config.source_dir) else Config.source_dir + x.removeprefix('/') for x in fs)))

    def parse_files_string(fs: str):
        return list(filter(None, (x.strip() for x in fs.splitlines())))