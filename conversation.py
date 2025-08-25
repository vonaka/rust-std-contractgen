import base64
import boto3
import pathlib
import sys
import time

import style

from botocore.exceptions import ClientError, ReadTimeoutError
from configuration import Config

class LongInputException(Exception):
    pass

class Conversation:

    def __init__(self, bedrock_model: str, bedrock_region: str, prompt_dir: str):
        # messages of this conversation
        self.msgs = []
        # directory of the prompt files
        self.prompt_dir = prompt_dir if prompt_dir.endswith('/') else prompt_dir + '/'
        # bedrock model used for this conversation
        self.bedrock_model = bedrock_model
        # bedrock region used for this model
        self.bedrock_region = bedrock_region
        # bedrock client for this conversation
        self.bedrock_client = boto3.client(
            service_name='bedrock-runtime', region_name=self.bedrock_region)
        # system prompts
        self.system_prompts = [{"text": ""}]
        # current checkpoint
        self.checkpoint = -1
        # reminder message
        self.reminder = ''

    def add_system_prompt(self, prompt_str: str = "", prompt_filename: str = ""):
        if prompt_str != "":
            self.system_prompts = [{"text": prompt_str}]
        elif prompt_filename != "":
            with open(self.prompt_dir + prompt_filename, 'r') as file:
                self.system_prompts = [{"text": file.read()}]

    def send_message(self, msg_str: str = "", msg_filename: str = ""):
        if msg_str != "":
            self.msgs.append({
                "role": "user",
                "content": [{
                    "text": msg_str
                }]
            })
        if msg_filename != "":
            with open(self.prompt_dir + msg_filename, 'r') as file:
                self.msgs.append({
                    "role": "user",
                    "content": [{
                        "text": file.read()
                    }]
                })

    def send_message_str(self, msg: str):
        self.send_message(msg_str=msg, msg_filename="")

    def send_message_from_file(self, filename: str):
        self.send_message(msg_str="", msg_filename=filename)

    def send_file(self, filename: str):
        self.msgs.append({
            "role": "user",
            "content": [{
                "document": {
                    "format": "txt",
                    "name": pathlib.Path(filename).stem,
                    "source": {
                        "bytes": Conversation.encode_file_to_base64(filename)
                    }
                }
            }]
        })

    def send_file_with_message(self, msg: str, filename: str):
        self.msgs.append({
            "role": "user",
            "content": [{"text": msg}, {
                "document": {
                    "format": "txt",
                    "name": pathlib.Path(filename).stem,
                    "source": {
                        "bytes": Conversation.encode_file_to_base64(filename)
                    }
                }
            }]
        })

    def set_checkpoint(self):
        self.checkpoint = len(self.msgs)-1

    def remove_checkpoint(self):
        if self.checkpoint != -1 and self.checkpoint < len(self.msgs):
            del self.msgs[self.checkpoint]
            self.checkpoint = -1

    # remove everything starting from (and including) checkpoint
    def remove_from_checkpoint(self):
        if self.checkpoint != -1 and self.checkpoint < len(self.msgs):
            self.msgs = self.msgs[:self.checkpoint]
            self.checkpoint = -1

    # remove everything before checkpoint, excluding the checkpoint itself
    def remove_till_checkpoint(self):
        if self.checkpoint != -1 and self.checkpoint < len(self.msgs):
            self.msgs = self.msgs[self.checkpoint:]
            self.checkpoint = 0

    def remove_all_except_checkpoint(self):
        if self.checkpoint != -1 and self.checkpoint < len(self.msgs):
            self.remove_till_checkpoint()
            self.msgs = self.msgs[:1]

    def converse(self):
        cleaned_conversation = False
        while True:
            try:
                if self.msgs == []:
                    Config.verboseprint(style.yellow("No messages to send"))
                    return ''
                inference_config = {"temperature": 0.0}
                response = self.bedrock_client.converse(
                    modelId=self.bedrock_model,
                    messages=self.msgs,
                    system=self.system_prompts,
                    inferenceConfig=inference_config,
                )
                rep_message = response['output']['message']
                if len(rep_message['content']) == 0:
                    return ''
                self.msgs.append(rep_message)
                i = 0
                out = ''
                while i < len(rep_message['content']):
                    if 'text' in rep_message['content'][i]:
                        out += rep_message['content'][i]['text']
                    i += 1
                return out
            except (TimeoutError, ReadTimeoutError):
                Config.verboseprint(
                    "Throttling (TimeoutError)... let me wait and try again in 4 minutes")
                time.sleep(240)
                continue
            except self.bedrock_client.exceptions.AccessDeniedException:
                print(style.red("Access Denied"))
                print(f'Make sure that the model ({self.bedrock_model}) is available in your region ({self.bedrock_region})')
                print(f'Configure the region in the config file: [worker_region|arbiter_region] = region')
                self.bedrock_client.close()
                sys.exit(1)
            except ClientError as excep:
                if excep.response['Error']['Code'] == 'ThrottlingException' or \
                   excep.response['Error']['Code'] == 'ServiceUnavailableException' or \
                   excep.response['Error']['Code'] == 'ReadTimeoutError':
                    Config.verboseprint(
                        f'Throttling ({excep.response['Error']['Code']})... let me wait and try again in 4 minutes')
                    time.sleep(240)
                    continue
                elif excep.response['Error']['Code'] == 'ExpiredTokenException':
                    print(style.red("Your credentials have expired"))
                    print("Please run `ada cred update --account <account> --role <role> --once`")
                    self.bedrock_client.close()
                    sys.exit(1)
                elif excep.response['Error']['Code'] == 'UnrecognizedClientException':
                    print(style.red("Unrecognized error"))
                    print("Try runing `mwinit` first")
                    self.bedrock_client.close()
                    sys.exit(1)
                elif excep.response['Error']['Code'] == 'ValidationException':
                    if "model identifier is invalid" in excep.response['Error']['Message']:
                        print(style.red(excep.response['Error']['Message']))
                        self.bedrock_client.close()
                        sys.exit(1)
                    elif "with on-demand throughput" in excep.response['Error']['Message']:
                        print(style.red(excep.response['Error']['Message']))
                        print("Try prefixing your model ID with 'us.'")
                        sys.exit(1)
                    elif cleaned_conversation and "Input is too long for requested model" in excep.response['Error']['Message']:
                        self.remove_from_checkpoint()
                        raise LongInputException
                    elif cleaned_conversation:
                        self.remove_all_except_checkpoint()
                        return ''
                    cleaned_conversation = True
                    Config.verboseprint(style.yellow("The conversation is way too long, let me shorten it"))
                    self.remove_till_checkpoint()
                    continue
                else:
                    raise

    def encode_file_to_base64(filename: str):
        with open(filename, 'rb') as file:
            return base64.b64encode(file.read()).decode('utf-8')

    def hi(self):
        self.send_message_str("Hi, are you there?")
        return self.converse()
