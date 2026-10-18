"""FastAPI 应用入口。"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from . import config
from .api.routes import router
from .services.workflow import workflow

app = FastAPI(title="三角洲行动 · 击杀集锦自动生成工具", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/config")
def get_config():
    """前端用于初始化校准面板的默认值。"""
    return {
        "id_region": config.DETECT.id_region.as_list(),
        "prompt_region": config.DETECT.prompt_region.as_list(),
        "knockdown_keywords": config.DETECT.knockdown_keywords,
        "sample_fps": config.DETECT.sample_fps,
        "debounce_seconds": config.DETECT.debounce_seconds,
        "id_match_ratio": config.DETECT.id_match_ratio,
        "clip_pre_seconds": config.CLIP.pre_seconds,
        "clip_post_seconds": config.CLIP.post_seconds,
        "detector_version": config.DETECTOR_VERSION,
    }


@app.on_event("startup")
def warmup():
    # 开机只监控目录；OCR 模型只在独立识别子进程中按需加载。
    workflow.start()


@app.on_event('shutdown')
def shutdown_workflow():
    workflow.stop()


# 常驻监控只需一个后端进程；构建后的页面也由同一端口提供，不常驻 Vite/Node。
_frontend = config.BASE_DIR.parent / 'frontend' / 'dist'
if _frontend.is_dir():
    app.mount('/', StaticFiles(directory=str(_frontend), html=True), name='frontend')
