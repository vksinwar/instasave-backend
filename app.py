# app.py
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from pydantic import BaseModel
import yt_dlp
import asyncio
from datetime import datetime, timedelta
import humanize
from typing import Dict, Optional, Callable, TypeVar, ParamSpec
from functools import wraps
import time
import httpx
import os

# Initialize FastAPI
app = FastAPI(title="Video Downloader API")

# Get allowed origins from environment variable or use default
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000").split(",")

# Enable CORS with configured origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Optimize Gzip compression
app.add_middleware(GZipMiddleware, minimum_size=500)

# Simple in-memory cache with size limit
MAX_CACHE_ITEMS = 100
cache: Dict[str, tuple[any, datetime]] = {}

# Cache cleanup function
async def cleanup_old_cache():
    while True:
        try:
            now = datetime.now()
            expired_keys = [
                k for k, v in cache.items() 
                if now - v[1] > timedelta(minutes=5)
            ]
            for k in expired_keys:
                del cache[k]
            
            # Keep cache size in check
            if len(cache) > MAX_CACHE_ITEMS:
                oldest_keys = sorted(
                    cache.keys(), 
                    key=lambda k: cache[k][1]
                )[:len(cache) - MAX_CACHE_ITEMS]
                for k in oldest_keys:
                    del cache[k]
                    
        except Exception:
            pass
        await asyncio.sleep(300)  # Run every 5 minutes

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(cleanup_old_cache())

class VideoURL(BaseModel):
    url: str

T = TypeVar('T')
P = ParamSpec('P')

def cache_response(expire_time: int = 300) -> Callable[[Callable[P, T]], Callable[P, T]]:
    def decorator(func: Callable[P, T]) -> Callable[P, T]:
        @wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            cache_key = f"{func.__name__}:{str(args)}:{str(kwargs)}"
            
            # Check cache
            if cache_key in cache:
                cached_value, timestamp = cache[cache_key]
                if datetime.now() - timestamp < timedelta(seconds=expire_time):
                    return cached_value
                else:
                    del cache[cache_key]
            
            response = await func(*args, **kwargs)
            
            # Only cache if we haven't exceeded the limit
            if len(cache) < MAX_CACHE_ITEMS:
                cache[cache_key] = (response, datetime.now())
            return response
        return wrapper
    return decorator

class VideoProcessor:
    def __init__(self, url: str):
        self.url = url
        self.ydl_opts = {
            'quiet': True,
            'format': 'best',
            'no_warnings': True,
            'socket_timeout': 10,  # Timeout for network operations
        }
    
    async def get_info(self) -> dict:
        with yt_dlp.YoutubeDL(self.ydl_opts) as ydl:
            return await asyncio.to_thread(ydl.extract_info, self.url, download=False)
    
    async def is_duration_valid(self, max_duration: int = 120) -> bool:
        try:
            info = await self.get_info()
            return info.get("duration", 0) <= max_duration
        except Exception:
            return False

@app.get("/")
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/video-downloader")
async def video_downloader(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/short-downloader")
async def short_downloader(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/reels-downloader")
async def reels_downloader(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/story-downloader")
async def story_downloader(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/highlights-downloader")
async def highlights_downloader(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/about")
async def about(request: Request):
    return templates.TemplateResponse("index.html", {"request": request, "section": "contact-section"})

@app.get("/privacy")
async def privacy(request: Request):
    return templates.TemplateResponse("index.html", {"request": request, "section": "privacy-section"})

@app.post("/video-info")
@cache_response(expire_time=300)
async def get_video_info(video: VideoURL):
    try:
        processor = VideoProcessor(video.url)
        info = await processor.get_info()
        
        if not info:
            raise HTTPException(status_code=400, detail="Could not fetch video information")

        return {
            'title': info.get('title', ''),
            'duration': humanize.precisedelta(info.get('duration', 0)),
            'thumbnail': info.get('thumbnail', ''),
            'format': info.get('format', ''),
            'valid': await processor.is_duration_valid()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/download")
async def download_video(video: VideoURL):
    try:
        processor = VideoProcessor(video.url)
        info = await processor.get_info()
        
        # Configure yt-dlp options
        ydl_opts = {
            'format': 'best',  # Download best quality
            'quiet': True,
            'no_warnings': True,
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # Get video info and URL
            video_info = ydl.extract_info(video.url, download=False)
            video_url = video_info['url']
            title = video_info.get('title', 'video')
            ext = video_info.get('ext', 'mp4')
            
            # Create async generator to stream the video
            async def video_stream():
                async with httpx.AsyncClient() as client:
                    async with client.stream('GET', video_url) as response:
                        async for chunk in response.aiter_bytes():
                            yield chunk
            
            # Return streaming response with proper filename
            return StreamingResponse(
                video_stream(),
                media_type='video/mp4',
                headers={
                    'Content-Disposition': f'attachment; filename="{title}.{ext}"'
                }
            )
            
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
