# Dashboard de Pólizas

App local para explorar la cartera desde Google Sheets o Excel, con KPIs, filtros, listados operativos, mapa de calor por localidad y módulo de escáner PDF.

## Importante sobre GitHub Pages

GitHub Pages solo publica archivos estáticos. La pantalla puede cargarse desde `dashboard/static`, pero las funciones que dependen del backend no funcionarán allí:

- lectura dinámica de Google Sheets desde Python
- escaneo de PDFs desde Google Drive
- guardado de plantillas
- escritura en Google Sheets
- chatbot local

Para que el escáner funcione online se debe desplegar `dashboard/server.py` en un servicio con Python, variables de entorno y credenciales seguras. No publiques la carpeta `Data/` ni credenciales JSON en GitHub.

## Ejecutar

```bash
./run_dashboard.sh
```

Por defecto levanta el dashboard en `http://127.0.0.1:8765`.

## Archivo fuente

- Google Sheet de cartera: `13q76_ri1EcVprHcmBYgoAMWWaynGWFscqSCUON8OC7E`
- Excel local opcional: `Data/listadopolizasexcel_20260420_174106.xlsx`

## Dependencias

```bash
python3 -m pip install -r requirements.txt
```

## Pruebas

```bash
python3 -m unittest discover dashboard/tests
```
