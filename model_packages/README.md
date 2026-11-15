# Transferencia del modelo de 24.621 imágenes

El experimento local de origen es `candidate-1a56d52ea49b4e41a2dbb7e1990c03f9`.
Su archivo Keras coincide byte por byte con el mejor checkpoint del ajuste
`combined-finetune01`. La instalación portátil se llama `dermavision-24621`.
El tamaño y el SHA-256 exactos están en
[`dermavision-24621/artifact.json`](dermavision-24621/artifact.json).

## Instalación en Windows

1. Copia `dermavision-24621.zip` desde la carpeta
   `DermaVision-transferencia` del Escritorio de la primera computadora.
   Usa una memoria USB o una transferencia privada y déjalo en Descargas.
2. Cierra el servidor de DermaVision y abre PowerShell en la raíz del
   repositorio de la otra computadora.

```powershell
git pull --ff-only origin main
if (!(Test-Path .venv\Scripts\python.exe)) { py -3.11 -m venv .venv }
.\.venv\Scripts\python.exe -m pip install -r requirements-web.txt
.\.venv\Scripts\python.exe setup_semantic_gate.py
.\.venv\Scripts\python.exe instalar_modelo_24621.py "$env:USERPROFILE\Downloads\dermavision-24621.zip"
Push-Location web
npm.cmd ci
npm.cmd run build
Pop-Location
.\INICIAR_WEB.cmd
```

El instalador valida el hash y escribe `runs/active_experiment.txt`.
React y Tkinter seleccionan el mismo experimento. En React, abre
`http://127.0.0.1:8765/#model` y comprueba el nombre `dermavision-24621`.
Para abrir temporalmente el original, ejecuta
`$env:DERMAVISION_EXPERIMENT = 'functional-02'` antes del lanzador.
Después de cerrar el servidor, elimina esa variable con
`Remove-Item Env:DERMAVISION_EXPERIMENT` para volver al modelo instalado.

El filtro semántico requiere una descarga única de CLIP
(`pytorch_model.bin`, cerca de 605 MB) mediante `setup_semantic_gate.py`.
El filtro de dominio también usa como referencia los pesos históricos
`runs/functional-02/model.keras` y los archivos de `domain-01` y `domain-02`
incluidos en Git. Las fotos de entrenamiento no son necesarias para clasificar.
Las funciones de imágenes de referencia requieren sus archivos locales.

## Evidencia y licencias

La carpeta `dermavision-24621` contiene calibración, configuración, historial
de las ocho épocas de ajuste, auditoría, métricas, predicciones y una
reproducción de la comparación. El manifiesto usa identificadores de muestra
y grupo sustitutos. Las rutas `images-local/` son marcadores y cada fila
conserva su fuente, grupo, etiqueta y partición. El mapa a los originales
se guarda solo en la máquina de origen.

El archivo Keras de 9.688.965 bytes y el candidato de 10.655.595 bytes caben
en Git normal. Git LFS está disponible, pero el tamaño no lo requiere.
La edición 2019 de ISIC declara condiciones de atribución y uso no comercial.
El ZIP original coincide en estructura y recuentos con una compilación
publicada en Kaggle, pero el ZIP de trabajo no acredita por sí solo esa
procedencia ni los permisos de redistribución de sus imágenes de origen.
Por esa incertidumbre, los pesos se prepararon para transferencia directa
entre tus equipos y el repositorio publica sus hashes y resultados.

- [Datos y atribuciones de ISIC](https://challenge.isic-archive.com/data/)
- [Compilación de Kaggle que coincide en estructura](https://www.kaggle.com/datasets/fanconic/skin-cancer-malignant-vs-benign)
- [PAD-UFES-20](https://data.mendeley.com/datasets/zr7vgbcyr2/1)
- [CLIP ViT-B/32](https://huggingface.co/openai/clip-vit-base-patch32)
- [Límites de archivos de GitHub](https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-large-files-on-github)

En `dermavision-50000` están la identidad del candidato, el historial y su
comparación. El ZIP privado `dermavision-50000-experimento.zip` contiene sus
pesos. Es un experimento separado y el instalador de 24.621 no lo acepta.

En la reproducción se comprobó la identidad de las 660 imágenes históricas
por hash de píxeles y se usaron los umbrales de ambos modelos sobre todas
ellas. Se repitieron las matrices de clasificación, con variación mínima en
el AUC al recalcular las puntuaciones. Es una prueba histórica ya consultada.
La revisión de duplicados exactos no descarta fotografías recortadas o
recomprimidas de la misma lesión, ni solapamientos por paciente.
