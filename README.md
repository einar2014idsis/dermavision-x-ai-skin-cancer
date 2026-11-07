# DermaVision-X

Prototipo de investigación para análisis experimental de imágenes de lesiones cutáneas y seguimiento fotográfico. Permite capturar o abrir imágenes, registrar visitas, comparar fotografías y generar informes y video de evolución.

**No es un dispositivo médico ni proporciona un diagnóstico.** Las puntuaciones del modelo no son probabilidades clínicas ni la precisión de una predicción individual. El índice de diferencias es descriptivo; la identidad de la lesión y el cambio físico no se verifican automáticamente. Cuando las imágenes no cumplen los controles, el sistema puede abstenerse de una medición temporal.

## Requisitos e instalación en Windows

Se requiere Python de 64 bits con Tkinter (se recomienda Python 3.11 o 3.12), conexión a internet para instalar dependencias y espacio para los modelos. En una terminal abierta en esta carpeta:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe setup_semantic_gate.py
```

El último comando descarga el modelo público `openai/clip-vit-base-patch32` en `runs/clip-vit-base-patch32`, necesario para el filtro semántico. Consulta sus condiciones de uso antes de distribuirlo. Para abrir seguimiento, ejecuta `INICIAR_SEGUIMIENTO.cmd`; para la cámara, `INICIAR_CAMARA.cmd`.

En el primer inicio crea un usuario y una contraseña de al menos 10 caracteres. No existe una contraseña predeterminada ni recuperación automática. El acceso es local y no cifra fotografías ni datos; protégelos mediante los controles de tu equipo. El historial y la credencial se guardan en `data/`, excluido del repositorio.

## Estructura

- `interfaz.py`: aplicación y análisis individual.
- `longitudinal_*.py`: registro de visitas, comparación, línea de tiempo e informe.
- `evolution_video.py`: exportación de video.
- `local_auth.py`, `login_ui.py`: acceso local.
- `domain_gate.py`, `semantic_gate.py`, `capture_guide.py`: controles de entrada y captura.
- `runs/functional-02/`: clasificador y resultados del experimento.
- `runs/domain-01/` y `runs/domain-02/`: parámetros de los filtros.
- `test_*.py`: pruebas automatizadas.

La copia incluye el modelo del clasificador, pero no las imágenes originales de entrenamiento ni las fotografías del usuario. En `manifest.csv` y `test_predictions.csv` se sustituyó el prefijo absoluto local por `dataset/`, manteniendo identificadores relativos, etiquetas y puntuaciones para preservar los gráficos del experimento. Son registros del experimento, no una copia de las imágenes: la búsqueda de imágenes de referencia requiere que el conjunto esté disponible en las rutas correspondientes. Antes de publicar, comprueba que cuentas con los permisos para distribuir los pesos y metadatos y documenta la procedencia y licencia del conjunto de datos.

## Pruebas

```powershell
.\.venv\Scripts\python.exe -m unittest discover -p "test_*.py"
```

Las pruebas automatizadas no sustituyen una evaluación clínica ni una prueba real de cámara y dispositivos. El experimento registrado indica que no se verificó la independencia por paciente ni el origen clínico; no deben presentarse sus métricas como rendimiento clínico. El clasificador y los filtros pueden equivocarse ante imágenes nuevas o sintéticas.

## Privacidad y publicación

No subas `data/`, credenciales, fotografías, bases de datos, entornos virtuales ni descargas del modelo CLIP al repositorio. Revisa los permisos de los archivos incluidos antes de publicar. El `.gitignore` conserva las configuraciones y el clasificador de este paquete y excluye los datos locales.

## Tecnologías y capacidades técnicas

El proyecto combina Python y Tkinter para la interfaz; TensorFlow/Keras para el clasificador experimental; PyTorch y Transformers para el filtro semántico; OpenCV y Pillow para imágenes; NumPy, scikit-learn y Matplotlib para análisis y visualización. `requirements.txt` contiene los rangos de versiones.

El flujo separa captura y controles de entrada, análisis individual, persistencia local y seguimiento longitudinal. Las herramientas de comparación, gráficos y generación de informes permiten revisar visitas y documentar cambios visuales; los módulos de calibración y evaluación respaldan la experimentación. Las salidas deben interpretarse dentro de las limitaciones descritas arriba, sin inferir rendimiento clínico.
