from PIL import Image
import numpy as np
from tensorflow.keras.models import load_model
from tensorflow.keras.applications.mobilenet_v2 import preprocess_input
import os

# Carga el modelo entrenado
model = load_model('fish_binary_classifier.h5')

# Mapeo de clases: verifica este diccionario cuando entrenas el modelo
class_indices = {'fish': 0, 'not_fish': 1}  

def is_fish_image(image_path: str, threshold: float = 0.5) -> str:
    img = Image.open(image_path).convert("RGB").resize((224, 224))
    x = np.array(img)
    x = preprocess_input(x)  # Correcto para MobileNetV2
    x = np.expand_dims(x, axis=0)
    prob = model.predict(x)[0][0]
    if class_indices['fish'] == 1:
        return f"{'Es un pescado' if prob >= threshold else 'No es un pescado'} ({prob:.2f})"
    else:
        return f"{'Es un pescado' if prob < threshold else 'No es un pescado'} ({prob:.2f})"

# Recorrer todas las imágenes de una carpeta
carpeta = r'C:\Users\jesus\Pictures\imagenes_pez\not_fish'
for nombre_archivo in os.listdir(carpeta):
    ruta_imagen = os.path.join(carpeta, nombre_archivo)
    if os.path.isfile(ruta_imagen):
        resultado = is_fish_image(ruta_imagen)
        print(f"{nombre_archivo}: {resultado}")
