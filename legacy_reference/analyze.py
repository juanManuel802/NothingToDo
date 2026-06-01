from preprocess import preprocess_image, preprocess_image_batch
import numpy as np
import os
import random
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '2'  # Solo muestra warnings y errores (no info)
import tensorflow as tf
from tensorflow.keras.preprocessing import image

# Cargar el modelo entrenado
model = tf.keras.models.load_model('../modelo_entrenado.h5')

# Procesa una sola imagen
def analyze_image(ruta_imagen, solo_ojo=False):
    seg_path, num_eyes = preprocess_image(ruta_imagen, solo_ojo=solo_ojo)  # Recibir el número de ojos
    img = image.load_img(seg_path, target_size=(224, 224))
    img_array = image.img_to_array(img) / 255.0
    img_array = np.expand_dims(img_array, axis=0)
    predicciones = model.predict(img_array)
    ojos_score = float(predicciones[0][0])
    piel_score = float(predicciones[0][1])

    calificacion_ojos = ojos_score * 5
    calificacion_piel = piel_score * 5

    if random.random() < 0.2:  # 20% de probabilidad
        calificacion_ojos = max(0, calificacion_ojos - 1)  # Asegura que no sea negativo
    if random.random() < 0.2:
        calificacion_piel = max(0, calificacion_piel - 1)

    anomalia_ojos = num_eyes > 1  

    return {
        "calificacion_ojos": round(calificacion_ojos, 2),
        "calificacion_piel": round(calificacion_piel, 2),
        "processed_image_path": seg_path,
        "anomalia": anomalia_ojos 
    }

# Procesa un batch de imágenes
def analyze_image_batch(rutas_imagen, solo_ojo=False):
    seg_paths = []
    batch_imgs = []
    anomalias_ojos = []  # Lista para guardar las anomalías de cada imagen
    for image_path in rutas_imagen:
        seg_path, num_eyes = preprocess_image(image_path, solo_ojo=solo_ojo)  # Recibir el número de ojos
        if seg_path is not None:
            seg_paths.append(seg_path)
            image_cv = cv2.imread(seg_path)
            image_resized = cv2.resize(image_cv, (224, 224))
            image_array = image_resized / 255.0
            batch_imgs.append(image_array)
            anomalia_ojos = num_eyes > 1  # Detectar anomalía si hay más de un ojo
            anomalias_ojos.append(anomalia_ojos)  # Guardar la información de anomalía
    batch_imgs = np.array(batch_imgs)
    predicciones = model.predict(batch_imgs)
    results = []
    for i, pred in enumerate(predicciones):
        ojos_score = float(pred[0])
        piel_score = float(pred[1])

        calificacion_ojos = ojos_score * 5
        calificacion_piel = piel_score * 5

        if random.random() < 0.2:  # 10% de probabilidad
            calificacion_ojos = max(0, calificacion_ojos - 1)  # Asegura que no sea negativo
        if random.random() < 0.2:
            calificacion_piel = max(0, calificacion_piel - 1)

        results.append({
            "image": rutas_imagen[i],
            "result": {
                "calificacion_ojos": round(calificacion_ojos, 2),
                "calificacion_piel": round(calificacion_piel, 2),
                "processed_image_path": seg_paths[i],
                "anomalia": anomalias_ojos[i]  # Retornar la información de anomalía
            }
        })
    return results