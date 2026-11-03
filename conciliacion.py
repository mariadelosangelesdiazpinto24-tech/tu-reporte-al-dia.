import os
import psycopg2
import psycopg2.extras
import urllib.parse as urlparse
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Optional
from fastapi import APIRouter, Request, Form, status
from fastapi.responses import RedirectResponse, HTMLResponse

router = APIRouter(prefix="/conciliacion", tags=["Conciliación Semanal"])

TZ_VENEZUELA = ZoneInfo("America/Caracas")

def obtener_fecha_venezuela() -> str:
    return datetime.now(TZ_VENEZUELA).strftime('%Y-%m-%d')

ALIAS_CONCILIACION = {
    "GRACHI": "GRACHIBABY",
    "GRACHIBABY": "GRACHIBABY",
    "JCPEREZ": "JC PEREZ",
    "RUTA MILLONARIA": "ANA MARIA",
    "LA SUERTE DE JANN": "NABEL",
    "DESTINO FORTUNA": "DESTINO SUERTE",
    "CAMINO DE LA SUERTE": "FERNANDO",
    "AGENCIA VALLEMIL": "VALLEMIL"
}

def normalizar(texto: str) -> str:
    import unicodedata
    if not texto:
        return ""
    texto = unicodedata.normalize('NFD', texto)
    texto = ''.join(c for c in texto if unicodedata.category(c) != 'Mn')
    t_clean = texto.strip().upper()
    return ALIAS_CONCILIACION.get(t_clean, t_clean)

def get_db():
    database_url = os.environ.get("DATABASE_URL")
    if database_url:
        if database_url.startswith("postgres://"):
            database_url = database_url.replace("postgres://", "postgresql://", 1)

        try:
            return psycopg2.connect(
                database_url,
                sslmode='require',
                connect_timeout=10,
                keepalives=1,
                keepalives_idle=30,
                keepalives_interval=10,
                keepalives_count=5,
                cursor_factory=psycopg2.extras.RealDictCursor
            )
        except Exception as e_direct:
            print("⚠️ [CONCILIACION] Reintentando conexión con parser:", e_direct)
            try:
                without_prefix = database_url.replace("postgresql://", "")
                auth_part, rest = without_prefix.split("@")
                user, password = auth_part.split(":", 1)
                host_port, dbname = rest.split("/")
                host, port = (host_port.split(":") if ":" in host_port else (host_port, "5432"))
                return psycopg2.connect(
                    dbname=dbname.split("?")[0],
                    user=user,
                    password=urlparse.unquote(password),
                    host=host,
                    port=port,
                    sslmode='require',
                    connect_timeout=10,
                    keepalives=1,
                    keepalives_idle=30,
                    keepalives_interval=10,
                    keepalives_count=5,
                    cursor_factory=psycopg2.extras.RealDictCursor
                )
            except Exception as e_parse:
                print("❌ [CONCILIACION] Error crítico de conexión:", e_parse)
                raise e_parse
    else:
        import sqlite3
        conn = sqlite3.connect("database.db", timeout=30.0)
        conn.row_factory = sqlite3.Row
        return conn

def init_tabla_conciliacion():
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS cierres_semanales_colab (
                id SERIAL PRIMARY KEY,
                agencia TEXT,
                desde_fecha TEXT,
                hasta_fecha TEXT,
                venta_real DOUBLE PRECISION DEFAULT 0,
                comision_real DOUBLE PRECISION DEFAULT 0,
                premios_real DOUBLE PRECISION DEFAULT 0,
                neto_real DOUBLE PRECISION DEFAULT 0,
                fecha_registro TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(agencia, desde_fecha, hasta_fecha)
            )
        ''')
        conn.commit()
        conn.close()
    except Exception as e:
        print("⚠️ [CONCILIACION] Aviso: No se pudo verificar la tabla al arrancar (se verificará en la primera petición):", e)

# Inicializa la tabla de forma segura sin interrumpir el despliegue
init_tabla_conciliacion()

# ------------------------------------------------------------------------------
# 1. API PARA CARGAR EL CIERRE CONSOLIDADO DESDE COLAB
# ------------------------------------------------------------------------------
@router.post("/api/cargar-cierre")
def api_cargar_cierre(
    agencia: str = Form(...),
    desde_fecha: str = Form(...),
    hasta_fecha: str = Form(...),
    venta_real: float = Form(0.0),
    comision_real: float = Form(0.0),
    premios_real: float = Form(0.0),
    neto_real: float = Form(0.0)
):
    ag_norm = normalizar(agencia)
    conn = get_db()
    cursor = conn.cursor()
    is_postgres = bool(os.environ.get("DATABASE_URL"))

    try:
        if is_postgres:
            cursor.execute("""
                INSERT INTO cierres_semanales_colab 
                (agencia, desde_fecha, hasta_fecha, venta_real, comision_real, premios_real, neto_real)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (agencia, desde_fecha, hasta_fecha) DO UPDATE SET
                    venta_real = EXCLUDED.venta_real,
                    comision_real = EXCLUDED.comision_real,
                    premios_real = EXCLUDED.premios_real,
                    neto_real = EXCLUDED.neto_real,
                    fecha_registro = CURRENT_TIMESTAMP
            """, (ag_norm, desde_fecha.strip(), hasta_fecha.strip(), float(venta_real), float(comision_real), float(premios_real), float(neto_real)))
        else:
            cursor.execute("""
                INSERT INTO cierres_semanales_colab 
                (agencia, desde_fecha, hasta_fecha, venta_real, comision_real, premios_real, neto_real)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (agencia, desde_fecha, hasta_fecha) DO UPDATE SET
                    venta_real = excluded.venta_real,
                    comision_real = excluded.comision_real,
                    premios_real = excluded.premios_real,
                    neto_real = excluded.neto_real,
                    fecha_registro = CURRENT_TIMESTAMP
            """, (ag_norm, desde_fecha.strip(), hasta_fecha.strip(), float(venta_real), float(comision_real), float(premios_real), float(neto_real)))

        conn.commit()
    except Exception as e:
        conn.rollback()
        print("❌ [CONCILIACION] Error al guardar cierre:", e)
        return {"status": "error", "mensaje": str(e)}
    finally:
        conn.close()

    return {"status": "ok", "mensaje": f"Cierre de {ag_norm} ({desde_fecha} a {hasta_fecha}) guardado con éxito."}

# ------------------------------------------------------------------------------
# 2. CÁLCULO DE LA COMPARACIÓN: COBRADO DÍA A DÍA VS COLAB
# ------------------------------------------------------------------------------
def calcular_balance_semanal(agencia: str, f_desde: str, f_hasta: str):
    ag_norm = normalizar(agencia)
    conn = get_db()
    cursor = conn.cursor()

    try:
        # Suma de los reportes diarios cobrados
        cursor.execute("""
            SELECT 
                COALESCE(SUM(ventas), 0) as total_venta,
                COALESCE(SUM(premios), 0) as total_premio,
                COALESCE(SUM(monto), 0) as total_neto,
                COUNT(*) as dias_registrados
            FROM reportes 
            WHERE UPPER(TRIM(agencia)) = %s AND fecha >= %s AND fecha <= %s
        """, (ag_norm, f_desde.strip(), f_hasta.strip()))
        cobrado = cursor.fetchone()

        v_cob = float(cobrado['total_venta'] or 0.0) if cobrado else 0.0
        p_cob = float(cobrado['total_premio'] or 0.0) if cobrado else 0.0
        n_cob = float(cobrado['total_neto'] or 0.0) if cobrado else 0.0
        dias_reg = cobrado['dias_registrados'] or 0 if cobrado else 0

        # Reporte de cierre de Colab
        cursor.execute("""
            SELECT * FROM cierres_semanales_colab
            WHERE UPPER(TRIM(agencia)) = %s AND desde_fecha = %s AND hasta_fecha = %s
            ORDER BY id DESC LIMIT 1
        """, (ag_norm, f_desde.strip(), f_hasta.strip()))
        colab = cursor.fetchone()

        if colab:
            v_real = float(colab['venta_real'] or 0.0)
            p_real = float(colab['premios_real'] or 0.0)
            com_real = float(colab['comision_real'] or 0.0)
            n_real = float(colab['neto_real'] or 0.0)
            tiene_colab = True
        else:
            v_real = p_real = com_real = n_real = 0.0
            tiene_colab = False

        return {
            "agencia": ag_norm,
            "desde_fecha": f_desde,
            "hasta_fecha": f_hasta,
            "dias_registrados": dias_reg,
            "tiene_colab": tiene_colab,
            "cobrado": {"venta": v_cob, "premio": p_cob, "neto": n_cob},
            "real": {"venta": v_real, "comision": com_real, "premio": p_real, "neto": n_real},
            "diferencia": {
                "venta": v_real - v_cob,
                "premio": p_real - p_cob,
                "neto": n_real - n_cob
            }
        }
    finally:
        conn.close()

# ------------------------------------------------------------------------------
# 3. APLICAR Y COBRAR LA DIFERENCIA AL SALDO
# ------------------------------------------------------------------------------
@router.post("/cobrar-diferencia")
def post_cobrar_diferencia(
    agencia: str = Form(...),
    desde_fecha: str = Form(...),
    hasta_fecha: str = Form(...),
    monto_diferencia: float = Form(...)
):
    ag_norm = normalizar(agencia)
    f_hasta_clean = hasta_fecha.strip()
    f_desde_clean = desde_fecha.strip()
    monto_val = float(monto_diferencia)

    if abs(monto_val) > 0.01:
        conn = get_db()
        cursor = conn.cursor()
        detalle = f"Ajuste Cuadre Semanal ({f_desde_clean} al {f_hasta_clean})"

        try:
            if monto_val > 0:
                cursor.execute("""
                    INSERT INTO pagos (agencia, fecha, monto, factura, comprobante, tipo, estado)
                    VALUES (%s, %s, %s, %s, 'Diferencia auditada en cierre semanal', 'AJUSTE_DEUDA', 'APROBADO')
                """, (ag_norm, f_hasta_clean, monto_val, detalle))
            else:
                cursor.execute("""
                    INSERT INTO pagos (agencia, fecha, monto, factura, comprobante, tipo, estado)
                    VALUES (%s, %s, %s, %s, 'Compensación a favor de cierre semanal', 'PAGO_BANCA', 'APROBADO')
                """, (ag_norm, f_hasta_clean, abs(monto_val), detalle))

            conn.commit()
        except Exception as e:
            conn.rollback()
            print("❌ [CONCILIACION] Error al registrar diferencia contable:", e)
        finally:
            conn.close()

    return RedirectResponse(
        url=f"/admin?tab=conciliacion_admin&agencia={ag_norm}&desde_fecha={f_desde_clean}&hasta_fecha={f_hasta_clean}&msg=conciliado",
        status_code=status.HTTP_303_SEE_OTHER
    )
