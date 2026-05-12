# Prudential & Brokers Dashboard

Dashboard local para cartera de pólizas y escáner de liquidaciones PDF.

## Ejecutar localmente

```bash
python3 -m pip install -r requirements.txt
./run_dashboard.sh
```

Abrir:

```text
http://127.0.0.1:8765
```

## Publicación

El repositorio incluye `.github/workflows/pages.yml` para publicar `dashboard/static` en GitHub Pages.

GitHub Pages no ejecuta Python. Para usar escaneo de PDF, plantillas, Google Sheets y chatbot en internet, despliega `dashboard/server.py` en un hosting con Python y configura las credenciales como secretos, nunca como archivos dentro del repositorio.

## Seguridad

La carpeta `Data/`, PDFs, Excel, CSV, capturas y credenciales locales están excluidas por `.gitignore`.
