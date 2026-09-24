# 📦 PROQUIM · Inteligencia de Pedidos La Favorita

App web en Streamlit para comparar el **stock que tiene La Favorita** con **lo que te pide**,
ver los patrones de los pedidos y **predecir el próximo pedido** por SKU.

## ¿Qué hace?

| Pestaña | Qué ves |
|---|---|
| 📊 **Resumen** | Stock total en el CD de Favorita, cobertura en días, pedido semanal promedio, SKUs en riesgo y el total estimado del próximo pedido. |
| ⚖️ **Stock vs Pedidos** | Tabla por SKU: stock actual, consumo semanal (sell-out), cobertura, pedido promedio, frecuencia y estado (⛔ Agotado · 🔴 Crítico · 🟠 Bajo · 🟢 OK · 🔵 Sobrestock). Gráfico de stock contra pedidos con recepciones detectadas y proyección de quiebre. |
| 🔍 **Patrones** | Qué día llegan los pedidos, tendencia por marca, mapa de calor SKU × semana y clasificación ABC-XYZ. |
| 🔮 **Predicción** | Pronóstico del próximo pedido por SKU con rango, probabilidad, señal ⬆️/⬇️, y columna para escribir tu **stock de bodega** y ver faltantes. Se descarga en Excel. |
| 🚚 **Cumplimiento** | Tiempo de entrega (pedido → llegada al CD) y cuánto se recibió frente a lo pedido. |
| 🗂️ **Datos** | Fuentes cargadas, tablas consolidadas y descarga. |

### Cómo predice
Compite con 5 modelos por SKU y se queda con el que menos se equivocó en las últimas 8 semanas:
promedio móvil, suavizamiento exponencial, Croston (pedidos intermitentes), **Reposición**
(aprende el stock objetivo al que Favorita repone y usa el stock actual del bot) y un ensamble.
Con tus datos históricos, el modelo de Reposición acierta ~66 % del volumen frente a ~49 % del promedio móvil.

---

## Fuentes de datos

```
 Gmail ──► Google Sheets "Historial_Pedidos" (columna K = cajas) ─┐
                                                                  ├──► App Streamlit
 Bot Selenium ──► Reporte_Existencias_*.xlsx ──► "Historial_Existencias" ─┘
                     (carpeta del escritorio)      (bot/subir_a_google_sheets.py)
 Data_forecast.xlsx (Matriz histórica) ──► carpeta data/ o subida manual
```

> **Importante:** Streamlit Cloud corre en internet, **no puede leer la carpeta de tu escritorio**.
> Por eso el bot sube cada reporte a una hoja de Google Sheets. Si corres la app en tu PC
> (`streamlit run app.py`), sí lee directamente `C:\Users\WELCOME\Desktop\FAVORTIA PROQUIM`.

---

## Puesta en marcha (paso a paso)

### 1. Cuenta de servicio de Google (una sola vez)
1. Entra a <https://console.cloud.google.com> → crea un proyecto (ej. `proquim-app`).
2. **APIs y servicios → Biblioteca**: habilita **Google Sheets API** y **Google Drive API**.
3. **Credenciales → Crear credenciales → Cuenta de servicio** → créala → pestaña **Claves → Agregar clave → JSON**. Se descarga un `.json`.
4. Abre tu Google Sheet → **Compartir** → pega el `client_email` del JSON (algo como `...@...iam.gserviceaccount.com`) con permiso **Editor**.

### 2. Conectar el bot
1. Copia `bot/subir_a_google_sheets.py` a la carpeta de tu bot y el JSON como `credenciales_google.json` al lado.
2. `pip install gspread google-auth openpyxl`
3. En tu bot, justo después de `wb.save(nuevo_nombre)` agrega:
   ```python
   from subir_a_google_sheets import subir_existencias
   subir_existencias(nuevo_nombre)
   ```
4. Sube de una vez todo lo que ya tienes descargado:
   ```
   python subir_a_google_sheets.py --carpeta "C:\Users\WELCOME\Desktop\FAVORTIA PROQUIM"
   ```
   Se crea la hoja **Historial_Existencias** automáticamente.

### 3. Publicar en Streamlit Cloud
1. Crea un repositorio **privado** en GitHub y sube esta carpeta (el `.gitignore` ya excluye las credenciales).
   - La carpeta `data/` trae tu Matriz histórica y un reporte de ejemplo; si no quieres subirlos, bórralos y cárgalos desde la app.
2. Entra a <https://share.streamlit.io> → **Create app** → elige el repo, rama `main`, archivo `app.py`.
3. **Advanced settings → Secrets**: pega el contenido de `.streamlit/secrets.toml.example` reemplazando la sección `[gcp_service_account]` con los datos de tu JSON.
4. **Deploy**. En la barra lateral → 🔌 Fuentes de datos, el interruptor *Google Sheets* se activa solo al detectar las credenciales.
5. (Recomendado) En la app publicada → **Settings → Sharing**: deja que solo tu equipo pueda verla.

### 4. Si Historial_Pedidos tiene otras columnas
La app detecta sola la fecha, el código de barras y el producto, y toma las **cajas de la columna K**.
Si algo no cuadra, ajústalo en la barra lateral → 🧭 *Columnas de Historial_Pedidos*.

---

## Ejecutar en tu PC
```
pip install -r requirements.txt
streamlit run app.py
```

## Estructura
```
app.py                     interfaz (pestañas, gráficos, tablas)
core/loaders.py            lectura de Excel del bot, Matriz, Google Sheets
core/analytics.py          stock vs pedidos, consumo, recepciones, ABC-XYZ
core/forecast.py           modelos de pronóstico + backtest
core/ui.py                 estilos y helpers de gráficos
bot/subir_a_google_sheets.py   para agregar a tu bot
.streamlit/config.toml     tema
.streamlit/secrets.toml.example  plantilla de credenciales
data/                      datos de ejemplo / históricos
```
