import os
from subprocess import run
from urllib.request import urlopen

from add_contracts import insert_requires
from configuration import Config
from conversation import Conversation


class Worker:

    def __init__(self):
        self.file_to_annotate = ''
        self.conversation = Conversation(Config.worker_model, Config.worker_region, Config.prompt_dir)

    def hi(self):
        self.conversation.add_system_prompt(prompt_str='Hi!')
        return self.conversation.hi()

    def generate_contracts(self):
        if self.file_to_annotate == '':
            self.generated_contracts = ''
            Config.verboseprint('No file to annotate')
            return ''

        Config.verboseprint(f'\nGenerating contracts for {self.file_to_annotate}')

        self.generated_contracts = ''

        self.copy_source_file()
        # TODO: Why not add this during initialization?
        self.conversation.add_system_prompt(
            prompt_filename='worker_system_prompt.txt')
        self.conversation.send_message_from_file('output_format.txt')
        self.attach_file()
        self.conversation.converse()
        self.conversation.send_message_from_file('worker_closing_refine.txt')
        self.generated_contracts = self.conversation.converse()
        return self.generated_contracts

    def generate_harnesses(self):
        if self.file_to_annotate == '' or self.generated_contracts == '':
            self.generated_harnesses = ''
            Config.verboseprint('No harnesses to generate')
            return ''

        Config.verboseprint(
            f'Generating harnesses for {self.file_to_annotate}')

        self.generated_harnesses = ''

        self.conversation.send_message_from_file('harnesses.txt')
        self.conversation.converse()

        res = "#[cfg(kani)] mod verify {use super::*;\n"
        for i, func in enumerate(self.list_of_updated_functions()):
            self.conversation.send_message_str(f'''
                Using the knowledge gained from steps 1-3, please write a `kani::proof_for_contract`
                for the function {func} that you annotated. Do not wrap it into `verify` module,
                just print the Rust code of the proof:
                
                ```rust
                <your code>
                ```

                Notes:
                - In your harnesses, for the bound for verification use small values: typically 10 is enough.
                - `kani::any()` can be used only with primitive types.
                - In the proof you cannot use types that are not defined in the scope, e.g., `Vec` is not
                  allowed.
            ''')
            out = self.conversation.converse()
            out = out.split("```rust\n")
            if len(out) > 1:
                res += "\n" + out[1].split("```")[0]

        if res == "#[cfg(kani)] mod verify {use super::*;\n":
            res = ''
        else:
            res += "}"
        self.generated_harnesses = res
        return self.generated_harnesses

    def autorefine_contracts(self):
        if self.file_to_annotate == '':
            self.generated_contracts = ''
            return ''

        Config.verboseprint(f'\tAutorefine contracts')

        self.generated_contracts = ''

        self.conversation.send_message_from_file('worker_autorefine.txt')
        self.conversation.converse()
        self.conversation.send_message_from_file('worker_closing_refine.txt')
        self.generated_contracts = self.conversation.converse()
        return self.generated_contracts

    def refine_contracts(self, instructions: str):
        Config.verboseprint(f'\t{Config.worker_model} refines its solution')

        self.conversation.send_message_str(instructions)
        self.conversation.converse()
        self.conversation.send_message_from_file('worker_closing_refine.txt')
        self.generated_contracts = self.conversation.converse()
        return self.generated_contracts

    def refine_harnesses(self, instructions: str):
        Config.verboseprint(f'\t{Config.worker_model} refines its solution')

        instructions += """
        Correct and print ALL your harnesses:
        ```rust
        <your_code> 
        ```
        """

        self.generated_harnesses = ''

        self.conversation.send_message_str(instructions)
        out = self.conversation.converse()
        out = out.split("```rust\n")
        res = "#[cfg(kani)] mod verify {use super::*;\n"
        if len(out) > 1:
            res += out[1].split("```")[0]
        if res != "#[cfg(kani)] mod verify {use super::*;\n":
            self.generated_harnesses = res + "}"

        return self.generated_harnesses

    def save_generated_contracts(self):
        if self.generated_contracts == '':
            return

        if self.generated_contracts.startswith("```rust\n"):
            self.generated_contracts = self.generated_contracts.split("```rust\n")[
                1].split("```")[0]

        Config.verboseprint(
            f'\tSaving the generated contracts into {Config.target_dir}{self.file_id}_contracts.rs')
        with open(Config.target_dir + self.file_id + "_contracts.rs", 'w') as f:
            f.write(self.generated_contracts)

        Config.verboseprint(
            f'\tApplying contracts to {Config.target_dir}{self.file_id}.rs')
        insert_requires(Config.target_dir + self.file_id + ".rs",
                        Config.target_dir + self.file_id + "_contracts.rs",
                        Config.target_dir + self.file_id + "_annotated.rs")

    def save_generated_harnesses(self):
        if self.generated_harnesses == '':
            return

        Config.verboseprint(f'\tSaving the generated harnesses')

        hf = Config.target_dir + self.file_id + "_harnesses.rs"
        af = Config.target_dir + self.file_id + "_annotated.rs"

        if not os.path.isfile(af):
            self.generated_harnesses = ''
            return

        with open(hf, 'w') as f:
            f.write(self.generated_harnesses)
        run(["rustfmt", hf], check=False, capture_output=True)
        with open(hf, 'r') as f1, open(af, 'a') as f2:
            f2.write(f1.read())

    def copy_source_file(self):
        Config.verboseprint(
            f'\tCopying the original file into {Config.target_dir}{self.file_id}.rs')

        os.makedirs(os.path.dirname(Config.target_dir), exist_ok=True)
        with open(Config.target_dir + self.file_id + ".rs", 'w') as file:
            file.write(self.source_code)

    def attach_file(self):
        Config.verboseprint(f'\tAnnotating with {Config.worker_model}')

        self.conversation.remove_checkpoint()
        self.conversation.send_file_with_message(
            """
            Please perform the translation of safety comments as described above on the
            following source code.
            """,
            Config.target_dir + self.file_id + ".rs")
        self.conversation.set_checkpoint()

    def set_file_to_annotate(self, file_to_annotate: str):
        self.generated_contracts = ''
        self.generated_harnesses = ''
        self.file_to_annotate = file_to_annotate
        relative_filename = file_to_annotate.removeprefix(Config.source_dir)
        self.file_id = relative_filename.split('.')[0].replace('/', '-')
        self.source_code = self.read_source_file()

    def read_source_file(self):
        if self.file_to_annotate.startswith('https://'):
            return urlopen(self.file_to_annotate).read().decode('utf-8')
        else:
            with open(self.file_to_annotate, 'r') as file:
                return file.read()

    def list_of_updated_functions(self):
        res = []
        if self.generated_contracts == '':
            return res

        ls = self.generated_contracts.split('\n')
        for (i, l) in enumerate(ls):
            if l.strip() == '':
                res.append(ls[i-1])
        if ls[-1].strip() != '':
            res.append(ls[-1])
        return res

    def log_summary(self):
        if self.generated_contracts == '':
            return
        n = len(self.list_of_updated_functions())
        Config.log(f'total number of annotated functions: {n}')
