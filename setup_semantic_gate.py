"""Descarga única de pesos públicos. No envía imágenes. Después funciona offline."""
from pathlib import Path
from huggingface_hub import snapshot_download

if __name__ == '__main__':
    destination = Path(__file__).parent / 'runs' / 'clip-vit-base-patch32'
    snapshot_download('openai/clip-vit-base-patch32',
                      revision='3d74acf9a28c67741b2f4f2ea7635f0aaf6f0268',
                      local_dir=destination,
                      allow_patterns=['config.json', 'preprocessor_config.json',
                                      'tokenizer_config.json', 'special_tokens_map.json',
                                      'vocab.json', 'merges.txt', 'pytorch_model.bin'])
    print(destination)
