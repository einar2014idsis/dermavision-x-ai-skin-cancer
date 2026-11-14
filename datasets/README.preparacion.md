# Preparación reproducible de datos ISIC

Estado: entorno y datos ISIC 2019 preparados; manifiesto generado y auditado. No se ha iniciado entrenamiento.

## Fuentes oficiales

- ISIC 2018 Task 3: 10.015 imágenes JPEG y diagnósticos one-hot. El archivo de agrupación identifica lesión (`lesion_id`). Licencia declarada por la página del reto: CC-BY-NC.
- ISIC 2019: 25.331 imágenes JPEG, diagnósticos one-hot y metadatos con `lesion_id` (sin paciente). Licencia: CC-BY-NC.
- SIIM-ISIC 2020: 33.126 imágenes, etiquetas originales, metadatos con paciente y lesión, y lista de 425 duplicados oficiales. Su etiqueta binaria `target` corresponde al objetivo melanoma del reto y no equivale a malignidad cutánea general.

Los paquetes originales se descargaron desde los enlaces S3 enlazados en https://challenge.isic-archive.com/data/. Se conservaron junto a sus CSV y deben permanecer inalterados. La licencia y la atribución se deben comprobar por imagen antes de redistribuir; el uso CC-BY-NC es no comercial y exige atribución.

## Conteos de etiquetas observados en ISIC 2019

MEL 4.522; NV 12.875; BCC 3.323; AK 867; BKL 2.624; DF 239; VASC 253; SCC 628. No se observó ninguna fila UNK positiva en el CSV de entrenamiento.

Para una tarea binaria exploratoria de malignidad general, la regla conservadora propuesta es:

- Maligno: MEL, BCC, SCC.
- Benigno: NV, BKL, DF, VASC.
- Excluir: AK (premaligna/ambigua para este binario), UNK y cualquier etiqueta no única.

ISIC 2018 AKIEC agrupa queratosis actínica/carcinoma intraepitelial y se excluye por la misma razón. Los registros 2018 se mantienen como fuente original, pero no se deben sumar a 2019 sin deduplicar imágenes: las ediciones contienen material de fuentes compartidas.

## Particiones y duplicados

No usar las particiones oficiales de retos como test clínico. Crear particiones nuevas agrupadas por lesión; para ISIC 2020 agrupar por paciente y lesión. ISIC 2019 no proporciona paciente, por lo que la separación por lesión es el máximo identificador disponible. Los identificadores ausentes deben quedar señalados como limitación.

El manifiesto base de ISIC 2019 agrupa por lesión y hash. Para combinarlo con
el ZIP histórico disponible localmente, usa el procedimiento de entrenamiento
combinado de esta guía. ISIC 2018 y 2020 se mantienen fuera de esa combinación.

## Entorno

WSL2 Ubuntu 24.04 está instalado. El entorno está en `/opt/dermavision/venv`; TensorFlow 2.21.0 y los requisitos del repositorio se instalaron. La prueba `smoke_model.py` completó construcción, actualización de pesos, inferencia, guardado y recarga en la RTX 4050. Los datasets extraídos para cómputo están en `/opt/dermavision/data/`; los ZIP y CSV originales se conservan bajo `datasets/raw/` en el proyecto Windows.

El modelo actual `runs/functional-02` se conserva. Sus métricas archivadas son exactitud 0,8303, sensibilidad 0,9333, especificidad 0,7444 y AUC 0,9370; independencia por paciente no verificada.

## Preparación del manifiesto binario

El script `preparar_isic2019.py` valida que exista cada archivo, verifica que abra, calcula SHA-256, excluye diagnósticos fuera del binario y duplicados exactos, agrupa imágenes por lesión y hash, y genera particiones estratificadas reproducibles. La salida conserva cada diagnóstico original en `manifest_all.csv`; `manifest.csv` contiene las filas incluidas y `audit.json` resume conteos y solapamientos de grupos.

Auditoría generada en esta preparación: 25.331 archivos presentes y legibles; 24.420 filas incluidas (15.964 benignas y 8.456 malignas); 50 filas pertenecen a grupos de duplicados exactos y 2 grupos duplicados presentaron etiquetas incompatibles; sin grupos compartidos entre train/validation/test. Las particiones tienen 19.780/2.198/2.442 filas. Estos conteos pueden variar si cambia el contenido o la versión de los archivos descargados.

En Ubuntu, abre la raíz del repositorio, ejecuta `source ./activar_entorno_wsl.sh` y define `RAW` con la ruta de las descargas. Después ejecuta:

```bash
python "preparar_isic2019.py" \
  --images /opt/dermavision/data/isic2019 \
  --ground-truth "$RAW/isic2019/ISIC_2019_Training_GroundTruth.csv" \
  --metadata "$RAW/isic2019/ISIC_2019_Training_Metadata.csv" \
  --output /opt/dermavision/prepared/isic2019
```

## Iniciar el entrenamiento cuando se autorice

Desde una consola Ubuntu de WSL, activar primero el entorno:

```bash
source "activar_entorno_wsl.sh"
```

ISIC 2019 está preparado para una primera corrida exploratoria con:

```bash
python "entrenar_isic2019.py" \
  --manifest /opt/dermavision/prepared/isic2019/manifest.csv \
  --output /opt/dermavision/runs/isic2019-run01 \
  --epochs 20 --batch-size 16
```

La corrida guardará un modelo por época, respaldo para reanudación, historial y predicciones/métricas del test. La selección de checkpoints usa validación; el test se consulta al final. Si se interrumpe, repetir el mismo comando añadiendo `--resume` reanuda desde el respaldo existente. El umbral inicial será 0,5: calibración y opción no concluyente se estimarán después usando exclusivamente validación.

## Entrenamiento combinado y ajuste de MobileNet

En WSL, desde el repositorio y con el entorno activado, apunta al ZIP original,
al manifiesto auditado de ISIC y a una carpeta nueva de salida:

```bash
python preparar_combinado.py --archive "$ZIP_PROPIO" \
  --historical runs/functional-02/manifest.csv --isic "$MANIFIESTO_ISIC" \
  --output "$DATOS_COMBINADOS"
python entrenar_isic2019.py --manifest "$DATOS_COMBINADOS/manifest.csv" --output "$BASE"
python afinar_mobilenet.py --manifest "$DATOS_COMBINADOS/manifest.csv" \
  --model "$BASE/model.keras" --output "$AJUSTE"
python comparar_modelos.py --manifest "$DATOS_COMBINADOS/manifest.csv" \
  --baseline "$BASE/model.keras" --candidate "$AJUSTE/candidate.keras" \
  --history "$AJUSTE/history.csv" --output "$PAQUETE"
```

La reconstrucción del manifiesto usa una nueva partición estratificada por
fuente y etiqueta. Para reproducir las cifras de una corrida existente, usa
su manifiesto original. El entrenador acepta también un manifiesto de prueba
externo mediante `--test-manifest`. Puede contener únicamente filas de prueba.

La comparación fija un umbral para cada modelo en validación. Busca al menos
90 % de sensibilidad global y maximiza la especificidad. El paquete se genera
si el candidato mejora el AUC global y mantiene el AUC, la sensibilidad y la
especificidad en la validación propia. El test histórico se registra como
evaluación de seguimiento.

Desde PowerShell, con la aplicación cerrada y su entorno local instalado:

```powershell
.\instalar_candidato.ps1 -Package $RutaDelPaquete
```

El instalador verifica la carga, el filtro y una clasificación antes de
activar el modelo para el siguiente inicio. Cada instalación conserva su
carpeta, de modo que una sesión abierta sigue asociada a su archivo Keras.
El historial registra el SHA-256 del archivo Keras y la calibración de cada análisis.

## Ampliación con fotos de celular y dermatoscopia

Descarga los tres ZIP originales y `metadata.csv` de PAD-UFES-20 v1
(https://data.mendeley.com/datasets/zr7vgbcyr2/1, CC BY 4.0) en
`raw/pad-ufes-20`. Conserva los CSV oficiales de ISIC 2020 en `raw/isic2020`.
Usa el manifiesto combinado original para mantener las mismas 2.435 imágenes
de validación histórica.

```bash
python preparar_ampliacion.py --manifest "$MANIFIESTO_COMBINADO" \
  --raw "$RAW" --isic2020-images "$ISIC2020_JPEG" --output "$AMPLIADO"
python afinar_mobilenet.py --manifest "$AMPLIADO/manifest.csv" \
  --model "$MODELO_ACTIVO" --output "$CORRIDA" --blocks 4 --epochs 10
```

El ensayo conserva los diagnósticos explícitos compatibles, revisa
coincidencias exactas después del preprocesamiento y divide PAD por grupos
de paciente y lesión. El informe incluye AUC sobre la validación original,
validación por fuente y prueba de celular por paciente. La meta de 0,93 se
compara sobre la validación original. El entrenamiento genera un candidato
para comparar y no altera la configuración de la aplicación.

## Corrida de 50.000 imágenes

La selección añade ejemplos de SLICE-3D al manifiesto ampliado hasta completar
50.000 filas de entrenamiento. Conserva los conjuntos de evaluación y excluye
coincidencias por identificador, lesión disponible y píxeles preprocesados.
Usa los tres archivos oficiales de ISIC 2024
(https://challenge.isic-archive.com/data/).

```bash
python preparar_50000.py --manifest "$AMPLIADO/manifest.csv" \
  --source "$RAW_2024" --output "$DATOS_50000"
python afinar_mobilenet.py --manifest "$DATOS_50000/manifest.csv" \
  --model "$MODELO_ACTIVO" --output "$CORRIDA_50000" --blocks 4 --epochs 10 \
  --external-weight 0.25 --original-validation-monitor
```

Los recortes de fotografía corporal reciben peso 0,25 antes de balancear las
clases. El checkpoint se selecciona sobre la validación original y
`comparison.json` contrasta su AUC con la meta de 0,93.
