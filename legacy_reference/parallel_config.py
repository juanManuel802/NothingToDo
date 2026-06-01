# Optimización del módulo Python para procesamiento paralelo
import os
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor
import multiprocessing as mp
from functools import lru_cache
import numpy as np

# ============================================================
# Configuración de threading y procesamiento paralelo
# ============================================================

# Detectar número de CPUs disponibles
NUM_CPUS = mp.cpu_count()
OPTIMAL_WORKERS = max(2, NUM_CPUS - 1)  # Dejar 1 CPU libre

# Configurar threads para librerías
os.environ['OMP_NUM_THREADS'] = str(OPTIMAL_WORKERS)
os.environ['MKL_NUM_THREADS'] = str(OPTIMAL_WORKERS)
os.environ['OPENBLAS_NUM_THREADS'] = str(OPTIMAL_WORKERS)
os.environ['NUMEXPR_NUM_THREADS'] = str(OPTIMAL_WORKERS)

# TensorFlow optimizations
os.environ['TF_NUM_INTRAOP_THREADS'] = str(OPTIMAL_WORKERS)
os.environ['TF_NUM_INTEROP_THREADS'] = '2'

print(f"🚀 Configuración paralela: {NUM_CPUS} CPUs detectados, usando {OPTIMAL_WORKERS} workers")

# ============================================================
# Thread pool global para operaciones I/O
# ============================================================
_io_executor = ThreadPoolExecutor(max_workers=OPTIMAL_WORKERS)

# ============================================================
# Process pool para preprocesamiento intensivo (opcional)
# ============================================================
_cpu_executor = ProcessPoolExecutor(max_workers=max(2, NUM_CPUS // 2))


def get_io_executor():
    """Obtener executor para operaciones I/O (lectura de archivos, HTTP, etc.)"""
    return _io_executor


def get_cpu_executor():
    """Obtener executor para procesamiento CPU intensivo"""
    return _cpu_executor


@lru_cache(maxsize=1)
def get_gpu_info():
    """Cache de información de GPU"""
    import subprocess
    
    gpu_info = {
        'type': 'cpu',
        'available': False,
        'name': 'CPU',
        'memory': 0
    }
    
    # Verificar NVIDIA
    try:
        result = subprocess.run(
            ['nvidia-smi', '--query-gpu=name,memory.total', '--format=csv,noheader,nounits'],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            name, memory = result.stdout.strip().split(',')
            gpu_info = {
                'type': 'nvidia',
                'available': True,
                'name': name.strip(),
                'memory': int(memory.strip())
            }
            print(f"✓ GPU NVIDIA: {gpu_info['name']} ({gpu_info['memory']} MB)")
            return gpu_info
    except:
        pass
    
    # Verificar AMD
    try:
        result = subprocess.run(['rocm-smi'], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            gpu_info = {
                'type': 'amd',
                'available': True,
                'name': 'AMD GPU',
                'memory': 0
            }
            print(f"✓ GPU AMD detectada")
            return gpu_info
    except:
        pass
    
    print("⚠ Usando CPU para procesamiento")
    return gpu_info


def configure_tensorflow():
    """Configurar TensorFlow para máximo rendimiento"""
    import tensorflow as tf
    
    gpu_info = get_gpu_info()
    
    if gpu_info['available']:
        # Configurar GPUs
        gpus = tf.config.list_physical_devices('GPU')
        if gpus:
            try:
                # Habilitar memory growth para no reservar toda la VRAM
                for gpu in gpus:
                    tf.config.experimental.set_memory_growth(gpu, True)
                
                # Configurar visible devices
                tf.config.set_visible_devices(gpus[:1], 'GPU')
                
                print(f"✓ TensorFlow configurado con {len(gpus)} GPU(s)")
            except RuntimeError as e:
                print(f"⚠ Error configurando GPU: {e}")
    else:
        # Optimizaciones CPU
        tf.config.threading.set_intra_op_parallelism_threads(OPTIMAL_WORKERS)
        tf.config.threading.set_inter_op_parallelism_threads(2)
        print(f"✓ TensorFlow configurado con {OPTIMAL_WORKERS} threads CPU")


def batch_generator(items, batch_size=8):
    """
    Generador de batches para procesamiento paralelo
    
    Args:
        items: Lista de items a procesar
        batch_size: Tamaño del batch (ajustar según memoria GPU)
    
    Yields:
        Batch de items
    """
    for i in range(0, len(items), batch_size):
        yield items[i:i + batch_size]


def parallel_map(func, items, use_processes=False, max_workers=None):
    """
    Mapeo paralelo de función sobre lista de items
    
    Args:
        func: Función a aplicar
        items: Lista de items
        use_processes: True para usar procesos (CPU intensive), False para threads (I/O)
        max_workers: Número de workers (None = automático)
    
    Returns:
        Lista de resultados
    """
    executor = _cpu_executor if use_processes else _io_executor
    
    if max_workers:
        # Crear executor temporal con workers específicos
        ExecutorClass = ProcessPoolExecutor if use_processes else ThreadPoolExecutor
        with ExecutorClass(max_workers=max_workers) as temp_executor:
            return list(temp_executor.map(func, items))
    else:
        return list(executor.map(func, items))


# ============================================================
# Cleanup al exit
# ============================================================
import atexit

def cleanup_executors():
    """Limpiar executors al cerrar"""
    _io_executor.shutdown(wait=True)
    _cpu_executor.shutdown(wait=True)
    print("✓ Executors cerrados correctamente")

atexit.register(cleanup_executors)


if __name__ == "__main__":
    # Test
    print(f"CPUs: {NUM_CPUS}")
    print(f"Workers: {OPTIMAL_WORKERS}")
    print(f"GPU Info: {get_gpu_info()}")
    
    # Configurar TensorFlow
    configure_tensorflow()
