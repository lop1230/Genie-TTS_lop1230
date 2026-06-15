import asyncio
import os
from typing import AsyncIterator, Optional, Callable, Union, Dict
import logging

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from .Audio.ReferenceAudio import ReferenceAudio
from .Core.TTSPlayer import tts_player
from .ModelManager import model_manager
from .Utils.Shared import context
from .Utils.Language import normalize_language

from pathlib import Path

logger = logging.getLogger(__name__)

_reference_audios: Dict[str, dict] = {}
SUPPORTED_AUDIO_EXTS = {'.wav', '.flac', '.ogg', '.aiff', '.aif'}

app = FastAPI()

# 项目根目录
_PROJECT_ROOT = Path(__file__).parent.parent.parent.resolve()

class TTSFastDefaultParameters(BaseModel):
    character_name: str = "feibi"
    onnx_model_dir: str = str(_PROJECT_ROOT / "CharacterModels" / "v2ProPlus" / "feibi" / "tts_models")
    save_path: str = str(_PROJECT_ROOT / "output.wav")
    reference_audio: str = str(_PROJECT_ROOT / "CharacterModels" / "v2ProPlus" / "feibi" / "prompt_wav" / "zh_vo_Main_Linaxita_2_1_10_26.wav")
    reference_audio_text: str = "在此之前，请您务必继续享受旅居拉古那的时光。"
    language: str = "Chinese"
    split_sentence: bool = True

TTS_default_parameters = TTSFastDefaultParameters()

class CharacterPayload(BaseModel):
    character_name: str
    onnx_model_dir: str
    language: str


class UnloadCharacterPayload(BaseModel):
    character_name: str


class ReferenceAudioPayload(BaseModel):
    character_name: str
    audio_path: str
    audio_text: str
    language: str


class TTSPayload(BaseModel):
    character_name: str
    text: str
    split_sentence: bool = False
    save_path: Optional[str] = None

class CurrentParametersResponse(BaseModel):
    character_name: str
    split_sentence: bool = False
    ReferenceAudio: str
    ReferenceAudioText: str
    language: str
    save_path: Optional[str] = None

@app.post("/load_character")
def load_character_endpoint(payload: CharacterPayload):
    try:
        model_manager.load_character(
            character_name=payload.character_name,
            model_dir=payload.onnx_model_dir,
            language=normalize_language(payload.language),
        )
        return {"status": "success", "message": f"Character '{payload.character_name}' loaded."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/unload_character")
def unload_character_endpoint(payload: UnloadCharacterPayload):
    try:
        model_manager.remove_character(character_name=payload.character_name)
        return {"status": "success", "message": f"Character '{payload.character_name}' unloaded."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/set_reference_audio")
def set_reference_audio_endpoint(payload: ReferenceAudioPayload):
    ext = os.path.splitext(payload.audio_path)[1].lower()
    if ext not in SUPPORTED_AUDIO_EXTS:
        raise HTTPException(
            status_code=400,
            detail=f"Audio format '{ext}' is not supported. Supported formats: {SUPPORTED_AUDIO_EXTS}",
        )
    _reference_audios[payload.character_name] = {
        'audio_path': payload.audio_path,
        'audio_text': payload.audio_text,
        'language': normalize_language(payload.language),
    }
    return {"status": "success", "message": f"Reference audio for '{payload.character_name}' set."}


def run_tts_in_background(
        character_name: str,
        text: str,
        split_sentence: bool,
        save_path: Optional[str],
        chunk_callback: Callable[[Optional[bytes]], None]
):
    try:
        context.current_speaker = character_name
        context.current_prompt_audio = ReferenceAudio(
            prompt_wav=_reference_audios[character_name]['audio_path'],
            prompt_text=_reference_audios[character_name]['audio_text'],
            language=_reference_audios[character_name]['language'],
        )
        tts_player.start_session(
            play=False,
            split=split_sentence,
            save_path=save_path,
            chunk_callback=chunk_callback,
        )
        tts_player.feed(text)
        tts_player.end_session()
        tts_player.wait_for_tts_completion()
    except Exception as e:
        logger.error(f"Error in TTS background task: {e}", exc_info=True)


async def audio_stream_generator(queue: asyncio.Queue) -> AsyncIterator[bytes]:
    while True:
        chunk = await queue.get()
        if chunk is None:
            break
        yield chunk


@app.post("/tts")
async def tts_endpoint(payload: TTSPayload):
    '''
    生成语音流
    请求参数：
    - character_name: 角色名称
    - text: 要转换为语音的文本
    - split_sentence: 是否按句子分隔
    - save_path: 保存路径(可选,带文件后缀名)
    '''
    if payload.character_name not in _reference_audios:
        raise HTTPException(status_code=404, detail="Character not found or reference audio not set.")

    loop = asyncio.get_running_loop()
    stream_queue: asyncio.Queue[Union[bytes, None]] = asyncio.Queue()

    def tts_chunk_callback(chunk: Optional[bytes]):
        loop.call_soon_threadsafe(stream_queue.put_nowait, chunk)

    loop.run_in_executor(
        None,
        run_tts_in_background,
        payload.character_name,
        payload.text,
        payload.split_sentence,
        payload.save_path,
        tts_chunk_callback
    )

    return StreamingResponse(audio_stream_generator(stream_queue), media_type="audio/wav")


@app.get("/stop")
def stop_endpoint():
    try:
        tts_player.stop()
        return {"status": "success", "message": "TTS stopped."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/clear_reference_audio_cache")
def clear_reference_audio_cache_endpoint():
    try:
        ReferenceAudio.clear_cache()
        return {"status": "success", "message": "Reference audio cache cleared."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/tts_fast")
async def tts_fast_endpoint(text: str):
    '''
    使用默认参数生成语音流
    请求参数：
    - text: 要转换为语音的文本
    - split_sentence: 是否按句子分隔
    '''
    if TTS_default_parameters.character_name not in _reference_audios:
        try:
            model_manager.load_character(
                character_name=TTS_default_parameters.character_name,
                model_dir=TTS_default_parameters.onnx_model_dir,
                language=normalize_language(TTS_default_parameters.language),
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
        ext = os.path.splitext(TTS_default_parameters.reference_audio)[1].lower()
        if ext not in SUPPORTED_AUDIO_EXTS:
            raise HTTPException(
                status_code=400,
                detail=f"Audio format '{ext}' is not supported. Supported formats: {SUPPORTED_AUDIO_EXTS}",
            )
        _reference_audios[TTS_default_parameters.character_name] = {
            'audio_path': TTS_default_parameters.reference_audio,
            'audio_text': TTS_default_parameters.reference_audio_text,
            'language': normalize_language(TTS_default_parameters.language),
        }   

    loop = asyncio.get_running_loop()
    stream_queue: asyncio.Queue[Union[bytes, None]] = asyncio.Queue()

    def tts_chunk_callback(chunk: Optional[bytes]):
        loop.call_soon_threadsafe(stream_queue.put_nowait, chunk)

    loop.run_in_executor(
        None,
        run_tts_in_background,
        TTS_default_parameters.character_name,
        text,
        TTS_default_parameters.split_sentence,
        TTS_default_parameters.save_path,
        tts_chunk_callback
    )

    return StreamingResponse(audio_stream_generator(stream_queue), media_type="audio/wav")

@app.get("/current_parameters")
def current_parameters_endpoint():
    '''
    获取当前参数
    '''
    message = CurrentParametersResponse(
        character_name=TTS_default_parameters.character_name,
        split_sentence=TTS_default_parameters.split_sentence,
        save_path=TTS_default_parameters.save_path,
        ReferenceAudio=TTS_default_parameters.reference_audio,
        ReferenceAudioText=TTS_default_parameters.reference_audio_text,
        language=TTS_default_parameters.language,
    )
    return {"status": "success", "message": message}

def start_server(host: str = "127.0.0.1", port: int = 8000, workers: int = 1):
    logger.info(f"Starting server on {host}:{port} with {workers} workers...")
    uvicorn.run(app, host=host, port=port, workers=workers)


if __name__ == "__main__":
    start_server(host="0.0.0.0", port=8000, workers=1)
