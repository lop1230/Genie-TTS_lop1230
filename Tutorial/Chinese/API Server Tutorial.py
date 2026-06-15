"""
启动 API 服务器，使用 genie.start_server(host=SERVER_HOST, port=SERVER_PORT, workers=1)。

Genie TTS 服务器 API 快速参考

1. 加载角色模型
端点：POST /load_character
功能：将角色模型加载到服务器中。
请求参数 (JSON)：
    - character_name (string)：角色的唯一名称。
    - onnx_model_dir (string)：服务器上模型文件夹的路径。
    - language (string)：模型语言（例如 'en', 'zh', 'jp'）。

2. 设置参考音频
端点：POST /set_reference_audio
功能：为已加载的角色设置声音克隆所需的参考音频。
请求参数 (JSON)：
    - character_name (string)：要设置的角色名称。
    - audio_path (string)：服务器上参考音频文件的路径。
    - audio_text (string)：与参考音频对应的文本。
    - language (string)：参考音频的语言（例如 'en', 'zh', 'jp'）。

3. 文本转语音 (TTS)
端点：POST /tts
功能：生成语音并以 audio/wav 流的形式返回。
请求参数 (JSON)：
    - character_name (string)：要使用的角色名称。
    - text (string)：要转换为语音的文本。
    - split_sentence (boolean, 可选)：是否自动拆分句子，默认为 false。
    - save_path (string, 可选)：在服务器上保存音频的完整路径。

4. 卸载角色模型
端点：POST /unload_character
功能：从服务器内存中移除角色以释放资源。
请求参数 (JSON)：
    - character_name (string)：要卸载的角色名称。

5. 停止所有 TTS 任务
端点：POST /stop
功能：立即停止所有正在进行的语音合成任务。
请求参数：无。

6. 清除参考音频缓存
端点：POST /clear_reference_audio_cache
功能：清除服务器上已加载的参考音频缓存。
请求参数：无。
"""

import time
import requests
import pyaudio
import multiprocessing

import genie_tts as genie

# --- 配置 ---
# 服务器地址
SERVER_HOST = "127.0.0.1"
SERVER_PORT = 8000
BASE_URL = f"http://{SERVER_HOST}:{SERVER_PORT}"

BYTES_PER_SAMPLE = 2
CHANNELS = 1
SAMPLE_RATE = 32000


def run_server():
    genie.start_server(host=SERVER_HOST, port=SERVER_PORT, workers=1)


def main_client():
    # 1. 加载角色
    print("\n[客户端] 第1步：正在发送加载角色请求...")
    load_payload = {
        "character_name": "<CHARACTER_NAME>",  # 替换为你的角色名称
        "onnx_model_dir": r"<PATH_TO_CHARACTER_ONNX_MODEL_DIR>",  # 替换为包含 ONNX 模型的文件夹路径
        "language": "<LANGUAGE_CODE>"  # 替换为语言代码，例如 'en', 'zh', 'jp'
    }
    try:
        response = requests.post(f"{BASE_URL}/load_character", json=load_payload)
        response.raise_for_status()
        print(f"[客户端] 角色加载成功：{response.json()['message']}")
    except requests.exceptions.RequestException as e:
        print(f"[客户端] 角色加载失败：{e}")
        return

    # 2. 设置参考音频
    print("\n[客户端] 第2步：正在发送设置参考音频请求...")
    ref_audio_payload = {
        "character_name": "<CHARACTER_NAME>",  # 使用与上面相同的角色名称
        "audio_path": r"<PATH_TO_REFERENCE_AUDIO>",  # 替换为你的参考音频文件路径
        "audio_text": "<REFERENCE_AUDIO_TEXT>",  # 替换为与参考音频对应的文本
        "language": "<LANGUAGE_CODE>"  # 替换为参考音频的语言，例如 'en', 'zh', 'jp'
    }
    try:
        response = requests.post(f"{BASE_URL}/set_reference_audio", json=ref_audio_payload)
        response.raise_for_status()
        print(f"[客户端] 参考音频设置成功：{response.json()['message']}")
    except requests.exceptions.RequestException as e:
        print(f"[客户端] 参考音频设置失败：{e}")
        return

    # 3. 请求 TTS 并播放音频流
    print("\n[客户端] 第3步：正在请求 TTS 并准备音频流...")
    tts_payload = {
        "character_name": "<CHARACTER_NAME>",  # 使用相同的角色名称
        "text": "<TEXT_TO_SYNTHESIZE>",  # 替换为你要合成的文本
        "split_sentence": True
    }

    p = pyaudio.PyAudio()
    stream = None

    try:
        with requests.post(f"{BASE_URL}/tts", json=tts_payload, stream=True) as response:
            response.raise_for_status()
            print("[客户端] 已连接到音频流，开始播放...")

            # 遍历接收到的音频块
            for chunk in response.iter_content(chunk_size=1024):
                if chunk:
                    if stream is None:
                        stream = p.open(format=p.get_format_from_width(BYTES_PER_SAMPLE),
                                        channels=CHANNELS,
                                        rate=SAMPLE_RATE,
                                        output=True)
                    stream.write(chunk)

            print("[客户端] 音频流播放完毕。")

    except requests.exceptions.RequestException as e:
        print(f"[客户端] TTS 请求失败：{e}")
    except Exception as e:
        print(f"[客户端] 播放过程中出现错误：{e}")
    finally:
        if stream:
            stream.stop_stream()
            stream.close()
        p.terminate()


if __name__ == "__main__":
    # 创建并启动服务器进程
    server_process = multiprocessing.Process(target=run_server)
    server_process.start()

    # 给服务器一些启动时间
    time.sleep(3)

    # 执行客户端逻辑
    try:
        main_client()
    finally:
        print("\n[主程序] 测试完成，正在关闭服务器...")
        server_process.terminate()
        server_process.join()
        print("[主程序] 服务器已关闭。")