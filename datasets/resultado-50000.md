# Resultado de la corrida de 50.000 imágenes

La corrida conservó 31.540 imágenes de entrenamiento de la ampliación anterior
y agregó 18.460 recortes de ISIC 2024. Las 2.747 imágenes de validación y las
972 imágenes de prueba estaban en particiones separadas. La evaluación final
de esta corrida usó la prueba reservada de 312 fotos de celular.

El modelo original se entrenó con 2.109 imágenes. El modelo que quedó activo
en el equipo se entrenó con 24.621. El candidato de 50.000 imágenes completó
siete épocas y conservó los pesos de la cuarta.

| AUC-ROC | Modelo activo | Candidato de 50.000 |
| --- | ---: | ---: |
| Validación original (2.435 imágenes) | 88,44 % | 88,17 % |
| Imágenes propias de validación (233 imágenes) | 93,02 % | 91,77 % |
| Prueba de celular (312 imágenes) | 84,16 % | 90,76 % |

La meta de 93 % en la validación original quedó pendiente. El candidato mejoró
en la prueba de celular y rindió peor en las imágenes propias. Se mantuvo el
modelo activo. El candidato y su comparación quedaron en el entorno local de
entrenamiento.
