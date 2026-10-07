from fastapi import FastAPI, Request, Form, File, UploadFile, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
import sqlite3
import os
import shutil

app = FastAPI()

# Configurar carpeta para guardar comprobantes de pago
UPLOADS_DIR = "uploads"
os.makedirs(UPLOADS_DIR, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=UPLOADS_DIR), name="uploads")

templates = Jinja2Templates(directory="templates")

# Base de datos SQLite
def init_db():
    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            rol TEXT NOT NULL
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS pagos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            agencia TEXT NOT NULL,
            fecha TEXT NOT NULL,
            factura TEXT NOT NULL,
            monto REAL NOT NULL,
            comprobante TEXT,
            estado TEXT DEFAULT 'PENDIENTE'
        )
    """)
    
    # Usuario Administrador por defecto
    cursor.execute("SELECT * FROM usuarios WHERE username = 'admin'")
    if not cursor.fetchone():
        cursor.execute("INSERT INTO usuarios (username, password, rol) VALUES ('admin', 'admin123', 'admin')")
    
    # Crear algunas agencias de ejemplo
    agencias_ejemplo = [('FENIX GOLD', '1234'), ('AG GEGE', '1234'), ('LADDLALOBA', '1234')]
    for user, pwd in agencias_ejemplo:
        cursor.execute("SELECT * FROM usuarios WHERE username = ?", (user,))
        if not cursor.fetchone():
            cursor.execute("INSERT INTO usuarios (username, password, rol) VALUES (?, ?, 'agencia')", (user, pwd))

    conn.commit()
    conn.close()

init_db()

# --- RUTAS DE NAVEGACIÓN ---

@app.get("/", response_class=HTMLResponse)
def vista_login(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.post("/login")
def login(username: str = Form(...), password: str = Form(...)):
    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    cursor.execute("SELECT username, password, rol FROM usuarios WHERE username = ?", (username.upper(),))
    user = cursor.fetchone()
    conn.close()

    if user and user[1] == password:
        if user[2] == "admin":
            return RedirectResponse(url="/admin", status_code=303)
        return RedirectResponse(url=f"/agencia?nombre={user[0]}", status_code=303)
    
    return RedirectResponse(url="/?error=1", status_code=303)

@app.get("/agencia", response_class=HTMLResponse)
def vista_agencia(request: Request, nombre: str = "AGENCIA"):
    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    cursor.execute("SELECT fecha, factura, monto, estado FROM pagos WHERE agencia = ? ORDER BY id DESC", (nombre,))
    historial = cursor.fetchall()
    conn.close()
    
    return templates.TemplateResponse("agencia.html", {
        "request": request,
        "nombre": nombre,
        "historial": historial
    })

@app.post("/agencia/guardar_pago")
async def guardar_pago(
    agencia: str = Form(...),
    fecha: str = Form(...),
    factura: str = Form(...),
    monto: float = Form(...),
    comprobante: UploadFile = File(...)
):
    # Guardar la foto/PDF del comprobante
    nombre_archivo = f"{agencia}_{factura}_{comprobante.filename}"
    ruta_guardado = os.path.join(UPLOADS_DIR, nombre_archivo)
    
    with open(ruta_guardado, "wb") as buffer:
        shutil.copyfileobj(comprobante.file, buffer)

    # Registrar en base de datos
    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO pagos (agencia, fecha, factura, monto, comprobante)
        VALUES (?, ?, ?, ?, ?)
    """, (agencia, fecha, factura, monto, nombre_archivo))
    conn.commit()
    conn.close()

    return RedirectResponse(url=f"/agencia?nombre={agencia}", status_code=303)

@app.get("/admin", response_class=HTMLResponse)
def vista_admin(request: Request):
    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    cursor.execute("SELECT id, agencia, fecha, factura, monto, comprobante, estado FROM pagos ORDER BY id DESC")
    pagos = cursor.fetchall()
    conn.close()
    
    return templates.TemplateResponse("admin.html", {"request": request, "pagos": pagos})