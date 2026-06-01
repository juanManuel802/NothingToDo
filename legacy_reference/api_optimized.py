# ============================================================
# API FastAPI Optimizada con Procesamiento Paralelo
# ============================================================
import time
import os
import sys
import glob
import asyncio
from typing import List, Optional
from concurrent.futures import ThreadPoolExecutor

from fastapi import FastAPI, Request, BackgroundTasks, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from pydantic import BaseModel, Field, validator
import uvicorn

# Importar configuración paralela
from parallel_config import (
    configure_tensorflow, 
    get_gpu_info, 
    parallel_map,
    batch_generator,
    get_io_executor
)

# Importar módulos de análisis
from analyze import analyze_image, analyze_image_batch
from fish_classifier_true import is_fish

# ============================================================
# Configuración inicial
# ============================================================
configure_tensorflow()
gpu_info = get_gpu_info()

# ============================================================
# Aplicación FastAPI
# ============================================================
app = FastAPI(
    title="SACP Python API",
    description="API de análisis de calidad de pescado con soporte GPU",
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# Middlewares
app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # En producción, especificar origen del Java app
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================
# Modelos de datos (Request/Response)
# ============================================================
class ImageRequest(BaseModel):
    image_path: str = Field(..., description="Ruta absoluta a la imagen")
    solo_ojo: bool = Field(default=False, description="Analizar solo el ojo")
    
    @validator('image_path')
    def validate_path(cls, v):
        if not os.path.exists(v):
            raise ValueError(f"Archivo no encontrado: {v}")
        if not v.lower().endswith(('.jpg', '.jpeg', '.png')):
            raise ValueError("Formato no soportado. Use JPG o PNG")
        return v


class BatchRequest(BaseModel):
    folder_path: str = Field(..., description="Ruta a carpeta con imágenes")
    solo_ojo: bool = Field(default=False, description="Analizar solo el ojo")
    max_images: Optional[int] = Field(default=None, description="Máximo de imágenes a procesar")
    
    @validator('folder_path')
    def validate_folder(cls, v):
        if not os.path.isdir(v):
            raise ValueError(f"Carpeta no encontrada: {v}")
        return v


class ImageListRequest(BaseModel):
    image_paths: List[str] = Field(..., description="Lista de rutas a imágenes")
    solo_ojo: bool = Field(default=False, description="Analizar solo el ojo")


class HealthResponse(BaseModel):
    status: str
    version: str
    gpu_available: bool
    gpu_type: str
    gpu_name: str
    workers: int


class AnalysisResponse(BaseModel):
    calificacion_ojos: float
    calificacion_piel: float
    processed_image_path: str
    anomalia: bool
    processing_time_seconds: float


# ============================================================
# Endpoints
# ============================================================
@app.get("/", response_model=dict)
async def root():
    """Endpoint raíz con información básica"""
    return {
        "api": "SACP Python API",
        "version": "2.0.0",
        "status": "running",
        "endpoints": {
            "health": "/health/",
            "docs": "/docs",
            "process": "/procesar/",
            "batch": "/procesar_batch/",
            "classify": "/es_pez/"
        }
    }


@app.get("/health/", response_model=HealthResponse)
async def health():
    """Health check con información del sistema"""
    return {
        "status": "ok",
        "version": "2.0.0",
        "gpu_available": gpu_info['available'],
        "gpu_type": gpu_info['type'],
        "gpu_name": gpu_info['name'],
        "workers": os.cpu_count()
    }


@app.post("/shutdown/")
async def shutdown():
    """Shutdown graceful (solo desarrollo)"""
    if os.getenv("NODE_ENV") == "production":
        raise HTTPException(status_code=403, detail="Shutdown no permitido en producción")
    
    async def stop_server():
        await asyncio.sleep(1)
        sys.exit(0)
    
    asyncio.create_task(stop_server())
    return {"status": "Shutting down..."}


@app.post("/es_pez/")
async def verificar_si_es_pez(request: ImageRequest):
    """
    Verificar si la imagen contiene un pez usando clasificador
    
    Args:
        request: ImageRequest con ruta de imagen
    
    Returns:
        Dict con resultado de clasificación
    """
    try:
        # Ejecutar en thread pool para no bloquear event loop
        loop = asyncio.get_event_loop()
        es_pez = await loop.run_in_executor(
            get_io_executor(),
            is_fish,
            request.image_path
        )
        
        return {
            "es_pez": bool(es_pez),
            "image_path": request.image_path
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al clasificar: {str(e)}")


@app.post("/procesar/", response_model=AnalysisResponse)
async def process_image(request: ImageRequest):
    """
    Procesar una imagen individual
    
    Args:
        request: ImageRequest con configuración
    
    Returns:
        Resultado del análisis
    """
    try:
        start_time = time.time()
        
        # Ejecutar en thread pool
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            get_io_executor(),
            analyze_image,
            request.image_path,
            request.solo_ojo
        )
        
        elapsed_time = time.time() - start_time
        result["processing_time_seconds"] = round(elapsed_time, 3)
        
        return result
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=f"Imagen no encontrada: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al procesar: {str(e)}")


@app.post("/procesar_batch/")
async def process_batch(request: BatchRequest):
    """
    Procesar batch de imágenes con procesamiento paralelo optimizado
    
    Args:
        request: BatchRequest con carpeta y configuración
    
    Returns:
        Resultados de análisis para todas las imágenes
    """
    try:
        # Buscar imágenes
        image_paths = (
            glob.glob(os.path.join(request.folder_path, "*.jpg")) +
            glob.glob(os.path.join(request.folder_path, "*.png")) +
            glob.glob(os.path.join(request.folder_path, "*.jpeg"))
        )
        
        if not image_paths:
            raise HTTPException(
                status_code=404, 
                detail="No se encontraron imágenes en la carpeta"
            )
        
        # Limitar cantidad si se especifica
        if request.max_images:
            image_paths = image_paths[:request.max_images]
        
        start_time = time.time()
        
        # Clasificar imágenes en paralelo (solo peces)
        loop = asyncio.get_event_loop()
        
        # Usar thread pool para clasificación paralela
        classification_tasks = [
            loop.run_in_executor(get_io_executor(), is_fish, img_path)
            for img_path in image_paths
        ]
        classifications = await asyncio.gather(*classification_tasks)
        
        # Filtrar solo imágenes de peces
        fish_image_paths = [
            img_path for img_path, is_fish_result 
            in zip(image_paths, classifications) 
            if is_fish_result
        ]
        
        if not fish_image_paths:
            return {
                "batch_results": [],
                "processing_time_seconds": round(time.time() - start_time, 3),
                "total_images": len(image_paths),
                "fish_images": 0,
                "message": "No se encontraron imágenes de pescado"
            }
        
        # Procesar batch de peces
        results = await loop.run_in_executor(
            None,  # Default executor
            analyze_image_batch,
            fish_image_paths,
            request.solo_ojo
        )
        
        elapsed_time = time.time() - start_time
        
        return {
            "batch_results": results,
            "processing_time_seconds": round(elapsed_time, 3),
            "total_images": len(image_paths),
            "fish_images": len(fish_image_paths),
            "images_per_second": round(len(fish_image_paths) / elapsed_time, 2)
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al procesar batch: {str(e)}")


@app.post("/procesar_lista/")
async def process_image_list(request: ImageListRequest):
    """
    Procesar lista específica de imágenes
    
    Args:
        request: ImageListRequest con lista de rutas
    
    Returns:
        Resultados de análisis
    """
    try:
        start_time = time.time()
        
        # Validar que existan
        valid_paths = [p for p in request.image_paths if os.path.exists(p)]
        if not valid_paths:
            raise HTTPException(status_code=404, detail="Ninguna imagen válida")
        
        loop = asyncio.get_event_loop()
        
        # Procesar batch
        results = await loop.run_in_executor(
            None,
            analyze_image_batch,
            valid_paths,
            request.solo_ojo
        )
        
        elapsed_time = time.time() - start_time
        
        return {
            "batch_results": results,
            "processing_time_seconds": round(elapsed_time, 3),
            "total_images": len(request.image_paths),
            "processed_images": len(valid_paths)
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


# ============================================================
# Manejador de errores global
# ============================================================
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Manejador global de excepciones"""
    return JSONResponse(
        status_code=500,
        content={
            "error": "Error interno del servidor",
            "detail": str(exc),
            "type": type(exc).__name__
        }
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Manejador de excepciones HTTP"""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": exc.detail,
            "status_code": exc.status_code
        }
    )


# ============================================================
# Startup y Shutdown
# ============================================================
@app.on_event("startup")
async def startup_event():
    """Inicialización al arrancar"""
    print("=" * 50)
    print("   SACP Python API - Iniciando")
    print("=" * 50)
    print(f"GPU: {gpu_info['name']} ({'Disponible' if gpu_info['available'] else 'No disponible'})")
    print(f"Workers: {os.cpu_count()}")
    print(f"Versión: 2.0.0")
    print("=" * 50)


@app.on_event("shutdown")
async def shutdown_event():
    """Limpieza al cerrar"""
    print("Cerrando API...")


# ============================================================
# Inicio de la aplicación (solo si se ejecuta directamente)
# ============================================================
if __name__ == "__main__":
    uvicorn.run(
        "api_optimized:app",
        host="0.0.0.0",
        port=8001,
        reload=True,
        workers=1,  # Para desarrollo
        log_level="info"
    )
