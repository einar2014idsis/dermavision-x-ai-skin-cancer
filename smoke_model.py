"""Prueba técnica con imágenes sintéticas. No genera un modelo clínico ni resultados científicos."""
import tempfile
from pathlib import Path
import numpy as np
import tensorflow as tf
from dermavision import build_model, metrics

tf.keras.utils.set_random_seed(2026)
model = build_model(weights=None)
x = np.random.default_rng(2026).uniform(0, 255, (4, 224, 224, 3)).astype('float32')
y = np.array([[0.], [1.], [0.], [1.]], dtype='float32')
model.train_on_batch(x, y)
before = model(x, training=False).numpy()
assert before.shape == (4, 1) and np.isfinite(before).all()
with tempfile.TemporaryDirectory() as tmp:
    path = Path(tmp) / 'smoke.keras'
    model.save(path)
    loaded = tf.keras.models.load_model(path)
    np.testing.assert_allclose(before, loaded(x, training=False).numpy(), atol=1e-6)
result = metrics(np.array([0, 0, 1, 1]), np.array([.1, .6, .4, .9]))
assert result['sensitivity'] == .5 and result['specificity'] == .5
assert result['confusion_matrix'] == [[1, 1], [1, 1]]
print('OK: construcción, actualización de pesos, inferencia, guardado, recarga y métricas.')
print('Prueba técnica sintética: NO se ha entrenado ni validado un clasificador clínico.')
