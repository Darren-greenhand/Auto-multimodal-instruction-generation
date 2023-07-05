#一个包装多进程的方法类
import openai
import json,time
from random import sample
from tqdm import tqdm

from utils import PP
import logging
import argparse


parser = argparse.ArgumentParser(description='Test for argparse')
parser.add_argument('--captiondata', "-d", help='json文件位置',required=True)
parser.add_argument('--num_processings',  help='声明进程数，默认值10', default=10)
parser.add_argument('--num_per_slice',  help='每个slice处理多少数据', default=128)
parser.add_argument('--num_icls',  help="选择ICL时使用几个上下文样例", default=5)
parser.add_argument('--output',  help="输出文件", default="instructions.json")
args = parser.parse_args()

num_icls = 0
nice_icl = False
icl_list = []
instructions = []

# 用的同事公司的API
OPENAI_API_KEY = ""
OPENAI_API_BASE = ""
# openai.api_type = "azure"
# openai.api_version = "2023-03-15-preview"
openai.api_base = OPENAI_API_BASE  # Your Azure OpenAI resource's endpoint value.
openai.api_key = OPENAI_API_KEY

def get_completion(prompt, model="gpt-3.5-turbo"):
    global nice_icl
    messages = [{"role": "user", "content": prompt}]
    try:
        response = openai.ChatCompletion.create(
            engine="gpt35", 
            model=model,
            messages=messages,
            temperature=0, # this is the degree of randomness of the model's output
        )
        res = response.choices[0].message["content"]

    #对长度的异常捕获，暂未实现
    # except openai.error.OpenAIError as e:
    #     logging.warning(f"OpenAIError: {e}.")
    #     if "Please reduce your prompt" in str(e):
    #         logging.warning(f"Reducing target length to {batch_decoding_args.max_tokens}, Retrying...")
    #         res = get_completion(prompt, model=model)
    #     else:
    #         logging.warning("Hit request rate limit; retrying...")
    #         time.sleep(30)  # Annoying rate limit on requests.
    #         res = get_completion(prompt, model=model)

    #对网络异常的捕获，不断重连
    except openai.error.APIConnectionError as e:
        print(f"Failed to connect to OpenAI API: {e}")
        time.sleep(5)  # Annoying rate limit on requests.
        res = get_completion(prompt, model=model)

    except openai.error.RateLimitError as e:
        print(f"OpenAI API request exceeded rate limit: {e}")
        pass
    except openai.error.Timeout as e:
        print(f"OpenAI API request timed out: {e}")
        pass
    except openai.error.InvalidRequestError as e:
        print(f"Invalid request to OpenAI API: {e}")
        pass
    except openai.error.AuthenticationError as e:
        print(f"Authentication error with OpenAI API: {e}")
        pass
    except openai.error.ServiceUnavailableError as e:
        print(f"OpenAI API service unavailable: {e}")
        pass
    
    print(res)
    return res


def generate(subcaption):
    global nice_icl
    global num_icls
    global icl_list

    # 最初的样例
    instruction = """
    Now I will show you a caption of an image, please raise a question about the image and answer it. \
    Please make sure that the question and answer are related to the image. \
    You should return question and answer after the caption as the following format: \
    Caption: A man is skiing in the open snow covered hills. \
    Question: What is the skier doing? \
    Answer: The skier is skiing in the snow-covered hills,making his way through the snow and enjoying thebeautiful mountain scenery.They are also standing near a trail sign,which indicates their locationon the mountain.\

    Caption: {}
    """
    # 用来检查icl是否合格，用形容词修饰确保icl质量（粗略）
    prompt_check = """
    Now I will give you a caption of an image, and a question and answer about the image. \
    if the question below is perfectly related to the caption, and the answer is totally correct while it can be found undoubtedly in the caption, \
    please output 1, otherwise output 0. \
    Caption: {} \
    Question: {} \
    Answer: {} \
    """

    # 用来引导用户使用icl的指导语，收集好examples后使用
    instruction_icl = """
    Now I will show you a caption of an image, please raise a question about the image and answer it. \
    Please make sure that the question and answer are related to the image. \
    Here are some examples: \
    {} \

    Caption: {} \
    """
    
    #收集的icl用样例
    icl = """
    Caption: {} \
    Question: {} \
    Answer: {} \
    """

    for idx,i in tqdm(enumerate(subcaption)):
        caption = i["caption"]
        # 冷启动，收集一些好的例子
        if nice_icl is not True:
            response = get_completion(instruction.format(caption), model="gpt-3.5-turbo")
            Q, A = response.split("Question:")[1].split("Answer:")
            Q = Q.strip()
            A = A.strip()
            if(len(Q)>0 and len(A)>0):
                response = get_completion(prompt_check.format(caption,Q,A), model="gpt-3.5-turbo")
                if "1" in response:
                    icl_list.append(icl.format(caption, Q, A))
                    num_icls += 1
            # 收集一些好的例子后，使用icl进行训练
            if num_icls >= args.num_icls:
                nice_icl = True 

        else:
            # 偶尔引入新的icl上下文，增加随机性
            if(idx%10==0):
                response = get_completion(instruction.format(caption), model="gpt-3.5-turbo")
                Q, A = response.split("Question:")[1].split("Answer:")
                Q = Q.strip()
                A = A.strip()
                response = get_completion(prompt_check.format(caption,Q,A), model="gpt-3.5-turbo")
                if "1" in response:
                    icl_list.append(icl.format(caption, Q, A))
                    num_icls += 1

            #icl_list中随机选取5个例子，用来构建比较优质的回答
            prompt_icl = "\n".join(sample(icl_list, args.num_icls))
            response = get_completion(instruction_icl.format(prompt_icl, caption), model="gpt-3.5-turbo")
            Q, A = response.split("Question:")[1].split("Answer:")
            Q = Q.strip()
            A = A.strip()
            
            instructions.append({"image_id": i["image_id"], "instruction": Q, "answer": A})
            
    with open(args.output,"a") as f:
        json.dump(instructions,f,indent=4)


#读入文件
with open(args.captiondata, "r") as f:
    caption = json.load(f)
caption = caption["annotations"] #list

#选择captions拆分粒度
start_pos = 0
num_slices = args.num_per_slice #每次每个进程处理128个数据

# 声明16个进程(我CPU是16核的)，每个处理一个slice数据
pp = PP(args.num_processings)
while start_pos < len(caption):
    end_pos = min(start_pos + num_slices, len(caption))
    pp.submit(generate, caption[start_pos:end_pos])
    start_pos = end_pos
pp.close()


