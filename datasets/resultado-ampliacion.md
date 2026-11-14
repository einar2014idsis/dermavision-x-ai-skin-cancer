# Cierre de la corrida con 31.540 imágenes

Se reutilizaron las 24.621 imágenes de entrenamiento del modelo instalado y se
sumaron 5.986 de ISIC 2020 y 933 de PAD-UFES-20. El ajuste partió de los pesos
del modelo instalado. La parada temprana terminó la corrida tras cuatro épocas
y el mejor checkpoint según el AUC de validación ampliada fue el de la primera.

| Evaluación | Modelo instalado | Candidato |
|---|---:|---:|
| AUC en la validación original (2.435 imágenes) | 88,44 % | 88,55 % |
| AUC en la validación propia (233 imágenes) | 93,02 % | 93,07 % |
| AUC en la prueba de celular (312 imágenes, pacientes reservados) | 84,16 % | 86,78 % |

Con un umbral por modelo elegido para obtener al menos 90 % de sensibilidad
en la validación original, el modelo instalado omitió 8 de 106 imágenes
malignas propias y el candidato omitió 11. Sus falsos positivos en ese
subconjunto fueron 29 y 27, respectivamente.

El candidato queda como experimento. Se mantiene activo el modelo anterior al
ajuste ampliado porque conserva mayor sensibilidad en las imágenes propias
con el criterio de selección acordado. El 93 % de AUC en la validación original
y las 50.000 imágenes de entrenamiento siguen pendientes.

Los resultados y el archivo Keras se guardaron en WSL bajo
`/opt/dermavision/runs/expanded01/`. El manifiesto ampliado está en
`/opt/dermavision/prepared/expanded01/manifest.csv`.
