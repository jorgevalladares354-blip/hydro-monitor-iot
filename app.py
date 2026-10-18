import json
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import streamlit as st

st.set_page_config(page_title='Hydro Monitor IoT', page_icon='💧', layout='wide')
st.markdown('''<style>.block-container{padding-top:1.7rem;max-width:1350px} [data-testid="stMetric"]{background:#10263c;border:1px solid #255270;border-radius:15px;padding:18px} [data-testid="stMetricLabel"]{color:#a7c8dd} h1,h2,h3{letter-spacing:-.02em}</style>''', unsafe_allow_html=True)
st.title('💧 HYDRO MONITOR IoT')
st.caption('Panel de monitoreo hidráulico · ESP32 · 2 sensores de presión · 3 caudalímetros · LoRa (pendiente)')
mode = st.sidebar.radio('Fuente de datos', ['Demostración', 'Archivo local del ESP32', 'Supabase (nube)'])
st.sidebar.caption('Los datos simulados no representan ensayos reales.')
refresh = st.sidebar.checkbox('Actualizar automáticamente cada 5 segundos', value=False)

PRESSURE = ['presion_1_bar', 'presion_2_bar']
FLOWS = ['caudal_1_l_min', 'caudal_2_l_min', 'caudal_3_l_min']
MEASURES = PRESSURE + FLOWS
COLUMNS = ['fecha_hora', 'caudal_l_min', 'volumen_l', 'sensor_id', 'estado', 'es_simulado'] + MEASURES
LABELS = {'presion_1_bar': 'Presión 1 (bar)', 'presion_2_bar': 'Presión 2 (bar)',
          'caudal_1_l_min': 'Caudal 1 (L/min)', 'caudal_2_l_min': 'Caudal 2 (L/min)',
          'caudal_3_l_min': 'Caudal 3 (L/min)'}


def empty_data():
    return pd.DataFrame(columns=COLUMNS)


def normalize(df, cloud=False):
    if df.empty:
        return empty_data()
    if 'fecha_hora' not in df.columns:
        st.error('Los datos deben contener la columna fecha_hora.')
        return empty_data()
    df = df.copy()
    if cloud:
        df['fecha_hora'] = pd.to_datetime(df['fecha_hora'], errors='coerce', utc=True).dt.tz_convert('America/Lima').dt.tz_localize(None)
    else:
        df['fecha_hora'] = pd.to_datetime(df['fecha_hora'], errors='coerce')
        if df['fecha_hora'].dt.tz is not None:
            df['fecha_hora'] = df['fecha_hora'].dt.tz_convert('America/Lima').dt.tz_localize(None)
    for col in MEASURES + ['caudal_l_min', 'volumen_l']:
        if col not in df.columns:
            df[col] = np.nan
        df[col] = pd.to_numeric(df[col], errors='coerce')
    for col in ['sensor_id', 'estado', 'es_simulado']:
        if col not in df.columns:
            df[col] = None
    return df.dropna(subset=['fecha_hora']).sort_values('fecha_hora').reset_index(drop=True)


def load_cloud():
    url = st.secrets.get('SUPABASE_URL', '').strip().rstrip('/')
    key = st.secrets.get('SUPABASE_KEY', '').strip()
    if not url or not key or 'PEGA_AQUI' in url or 'PEGA_AQUI' in key:
        st.error('Falta configurar SUPABASE_URL o SUPABASE_KEY en los Secrets de Streamlit Cloud.')
        return empty_data()
    params = urlencode({'select': ','.join(COLUMNS), 'order': 'fecha_hora.desc', 'limit': '500'})
    request = Request(f'{url}/rest/v1/mediciones?{params}', headers={'apikey': key, 'Accept': 'application/json'})
    try:
        with urlopen(request, timeout=12) as response:
            records = json.load(response)
        if not isinstance(records, list):
            st.error('Supabase no devolvió una lista de mediciones.')
            return empty_data()
        return normalize(pd.DataFrame(records), cloud=True)
    except HTTPError as exc:
        st.error(f'No se pudo consultar Supabase (HTTP {exc.code}). Revisa la clave, URL y política SELECT.')
    except (URLError, TimeoutError, ValueError, OSError) as exc:
        st.error(f'No se pudo consultar Supabase: {type(exc).__name__}. Comprueba la conexión y configuración.')
    return empty_data()


def load_data():
    if mode == 'Demostración':
        ts = pd.date_range(end=datetime.now(), periods=60, freq='min')
        x = np.linspace(0, 9, 60)
        df = pd.DataFrame({
            'fecha_hora': ts,
            'presion_1_bar': (1.30 + .12 * np.sin(x)).round(3),
            'presion_2_bar': (1.18 + .10 * np.sin(x + .3)).round(3),
            'caudal_1_l_min': (2.6 + .35 * np.sin(x)).round(3),
            'caudal_2_l_min': (2.4 + .32 * np.sin(x + .15)).round(3),
            'caudal_3_l_min': (2.2 + .29 * np.sin(x + .3)).round(3),
            'es_simulado': True,
        })
        return normalize(df), True
    if mode == 'Supabase (nube)':
        return load_cloud(), False
    path = Path(__file__).resolve().parent / 'datos' / 'mediciones.csv'
    if not path.exists():
        return empty_data(), False
    try:
        return normalize(pd.read_csv(path)), False
    except (OSError, ValueError, pd.errors.ParserError) as exc:
        st.error(f'No se pudo leer el historial: {exc}')
        return empty_data(), False


def latest_value(df, col):
    valid = df.dropna(subset=[col]) if not df.empty else df
    return float(valid.iloc[-1][col]) if not valid.empty else None


def integrated_volume(df, col):
    if df.empty:
        return None
    valid = df.dropna(subset=[col]).copy()
    if valid.empty:
        return None
    seconds = valid['fecha_hora'].diff().dt.total_seconds()
    intervals = seconds.where((seconds > 0) & (seconds <= 120), 0).fillna(0)
    previous = valid[col].shift(1).fillna(valid[col])
    return float(((valid[col] + previous) / 2 * intervals / 60).sum())


def render():
    df, demo = load_data()
    if demo:
        st.warning('MODO DEMOSTRACIÓN · Los cinco sensores muestran datos simulados, NO mediciones reales.')
    elif mode == 'Supabase (nube)':
        st.info('DATOS EN LA NUBE · Historial almacenado en Supabase. No confirma conexión activa del ESP32.')
        if not df.empty and 'es_simulado' in df.columns and df['es_simulado'].fillna(False).astype(str).str.lower().isin(['true', '1', 'yes']).any():
            st.warning('Este historial contiene registros simulados o de prueba. No usarlos como resultados experimentales.')
    elif df.empty:
        st.info('SIN LECTURAS · Esperando archivo datos/mediciones.csv con las nuevas columnas.')

    st.subheader('🧭 Sensores de presión')
    pcols = st.columns(2)
    for i, col in enumerate(PRESSURE):
        value = latest_value(df, col)
        pcols[i].metric(f'Presión {i+1}', f'{value:.3f} bar' if value is not None else '—')

    st.subheader('💧 Caudalímetros')
    qcols = st.columns(3)
    for i, col in enumerate(FLOWS):
        value = latest_value(df, col)
        qcols[i].metric(f'Caudal {i+1}', f'{value:.3f} L/min' if value is not None else '—')

    p1, p2 = (latest_value(df, c) for c in PRESSURE)
    q1, q2, q3 = (latest_value(df, c) for c in FLOWS)
    st.subheader('📊 Indicadores de seguimiento')
    a, b, c, d = st.columns(4)
    a.metric('Diferencia de presión P1 − P2', f'{p1-p2:+.3f} bar' if p1 is not None and p2 is not None else '—')
    b.metric('Diferencia de caudal Q1 − Q3', f'{q1-q3:+.3f} L/min' if q1 is not None and q3 is not None else '—')
    dtime = df.iloc[-1]['fecha_hora'].strftime('%Y-%m-%d %H:%M:%S') if not df.empty else '—'
    c.metric('Registros cargados', str(len(df)))
    d.metric('Fuente', 'Demostración' if demo else ('Supabase' if mode == 'Supabase (nube)' else 'Archivo local'))
    st.caption(f'Último registro: {dtime} (hora de Perú para Supabase). Diferencias orientativas: no constituyen por sí solas diagnóstico de fugas.')

    st.subheader('📈 Evolución de la presión')
    available_p = [col for col in PRESSURE if not df.empty and df[col].notna().any()]
    if available_p:
        st.line_chart(df.set_index('fecha_hora')[available_p].rename(columns=LABELS), y_label='bar')
    else:
        st.info('No hay lecturas de presión todavía.')

    st.subheader('📈 Evolución del caudal')
    available_q = [col for col in FLOWS if not df.empty and df[col].notna().any()]
    if available_q:
        st.line_chart(df.set_index('fecha_hora')[available_q].rename(columns=LABELS), y_label='L/min')
    else:
        st.info('No hay lecturas de los tres caudalímetros todavía.')

    st.subheader('🚰 Volumen integrado estimado')
    vcols = st.columns(3)
    for i, col in enumerate(FLOWS):
        volume = integrated_volume(df, col)
        vcols[i].metric(f'Volumen caudalímetro {i+1}', f'{volume:.3f} L' if volume is not None else '—')
    st.caption('Integración trapezoidal del caudal: intervalos mayores a 120 segundos se excluyen. No equivale a volumen medido directamente.')

    st.subheader('📋 Historial de mediciones')
    if not df.empty:
        names = {'fecha_hora': 'Fecha y hora', 'caudal_l_min': 'Caudal antiguo (L/min)',
                 'volumen_l': 'Volumen registrado (L)', 'sensor_id': 'Sensor',
                 'estado': 'Estado del registro', 'es_simulado': 'Simulado', **LABELS}
        display = df.rename(columns=names).sort_values('Fecha y hora', ascending=False)
        st.dataframe(display, use_container_width=True, hide_index=True)
        filename = 'hidro_demo_5_sensores.csv' if demo else ('hidro_supabase_5_sensores.csv' if mode == 'Supabase (nube)' else 'hidro_mediciones_5_sensores.csv')
        st.download_button('⬇ Descargar CSV', data=display.to_csv(index=False).encode('utf-8-sig'), file_name=filename, mime='text/csv')
    else:
        st.caption('No hay mediciones guardadas.')
    st.caption('La conexión Supabase es de solo lectura. Para recibir datos reales habrá que actualizar el programa del ESP32 y su sistema de envío a la nube.')


if refresh:
    @st.fragment(run_every='5s')
    def live_panel():
        render()
else:
    def live_panel():
        render()

live_panel()
