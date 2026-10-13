import json
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import numpy as np
import pandas as pd
import streamlit as st

st.set_page_config(page_title='Hydro Monitor IoT', page_icon='💧', layout='wide')
st.markdown('''<style>.block-container{padding-top:1.7rem;max-width:1350px} [data-testid="stMetric"]{background:#10263c;border:1px solid #255270;border-radius:15px;padding:18px} [data-testid="stMetricLabel"]{color:#a7c8dd} h1,h2,h3{letter-spacing:-.02em}</style>''', unsafe_allow_html=True)
st.title('💧 HYDRO MONITOR IoT')
st.caption('Panel de monitoreo hidráulico · ESP32 · Caudalímetro · LoRa (pendiente)')
mode = st.sidebar.radio('Fuente de datos', ['Demostración', 'Archivo local del ESP32', 'Supabase (nube)'])
st.sidebar.caption('Los datos simulados no representan ensayos reales.')
refresh = st.sidebar.checkbox('Actualizar automáticamente cada 5 segundos', value=False)

COLUMNS = ['fecha_hora', 'caudal_l_min', 'volumen_l', 'sensor_id', 'estado', 'es_simulado']


def empty_data():
    return pd.DataFrame(columns=COLUMNS)


def normalize(df, cloud=False):
    if df.empty:
        return empty_data()
    if not {'fecha_hora', 'caudal_l_min'}.issubset(df.columns):
        st.error('Los datos deben contener fecha_hora y caudal_l_min.')
        return empty_data()
    df = df.copy()
    if cloud:
        # Las marcas de Supabase son UTC; se presentan en hora de Perú.
        df['fecha_hora'] = pd.to_datetime(df['fecha_hora'], errors='coerce', utc=True).dt.tz_convert('America/Lima').dt.tz_localize(None)
    else:
        df['fecha_hora'] = pd.to_datetime(df['fecha_hora'], errors='coerce')
    df['caudal_l_min'] = pd.to_numeric(df['caudal_l_min'], errors='coerce')
    return df.dropna(subset=['fecha_hora', 'caudal_l_min']).sort_values('fecha_hora').reset_index(drop=True)


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
        q = np.maximum(0, 2.4 + .35*np.sin(np.linspace(0, 9, 60)) + .1*np.cos(np.linspace(0, 25, 60)))
        return pd.DataFrame({'fecha_hora': ts, 'caudal_l_min': q.round(3), 'es_simulado': True}), True
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


def render():
    df, demo = load_data()
    if demo:
        st.warning('MODO DEMOSTRACIÓN · Datos simulados, NO mediciones del caudalímetro.')
    elif mode == 'Supabase (nube)':
        st.info('DATOS EN LA NUBE · Historial almacenado en Supabase. No implica conexión activa del ESP32.')
        if not df.empty and 'es_simulado' in df.columns and df['es_simulado'].fillna(False).astype(bool).any():
            st.warning('Este historial contiene registros de prueba/simulados. No utilizarlos como resultados experimentales.')
    elif df.empty:
        st.info('SIN LECTURAS · Ejecuta receptor_esp32.py cuando el ESP32 esté conectado y transmitiendo.')

    if not df.empty:
        last = df.iloc[-1]
        flow = float(last['caudal_l_min'])
        seconds = df['fecha_hora'].diff().dt.total_seconds()
        intervals = seconds.where((seconds > 0) & (seconds <= 120), 0).fillna(0)
        volume = ((df['caudal_l_min'] + df['caudal_l_min'].shift(1).fillna(df['caudal_l_min'])) / 2 * intervals / 60).sum()
        if demo:
            state = 'Demostración'
        elif mode == 'Supabase (nube)':
            state = 'Historial nube'
        else:
            age = (datetime.now() - last['fecha_hora'].to_pydatetime()).total_seconds()
            state = 'Datos recientes' if -10 <= age <= 15 else 'Sin señal reciente'
        last_time = last['fecha_hora'].strftime('%Y-%m-%d %H:%M:%S')
    else:
        flow = None
        volume = None
        state = 'Sin datos'
        last_time = '—'

    a, b, c, d = st.columns(4)
    a.metric('Último caudal registrado' if mode == 'Supabase (nube)' else 'Caudal actual', f'{flow:.2f} L/min' if flow is not None else '—')
    b.metric('Volumen integrado (estimado)', f'{volume:.3f} L' if volume is not None else '—')
    c.metric('Estado', state)
    d.metric('Registros cargados', str(len(df)))
    st.caption(f'Última lectura (hora Perú en modo nube): {last_time} · Volumen estimado por integración; intervalos mayores a 120 s se excluyen. En modo nube se consultan hasta 500 registros recientes.')
    st.subheader('📈 Evolución del caudal')
    if not df.empty:
        st.line_chart(df.set_index('fecha_hora')['caudal_l_min'], y_label='L/min')
    else:
        st.info('El gráfico aparecerá cuando existan lecturas.')
    st.subheader('📋 Historial')
    if not df.empty:
        display = df.rename(columns={'fecha_hora': 'Fecha y hora', 'caudal_l_min': 'Caudal (L/min)', 'volumen_l': 'Volumen registrado (L)', 'sensor_id': 'Sensor', 'estado': 'Estado del registro', 'es_simulado': 'Simulado'})
        st.dataframe(display.sort_values('Fecha y hora', ascending=False), width='stretch', hide_index=True)
        filename = 'hidro_demo.csv' if demo else ('hidro_supabase.csv' if mode == 'Supabase (nube)' else 'hidro_mediciones.csv')
        st.download_button('⬇ Descargar CSV', data=display.to_csv(index=False).encode('utf-8-sig'), file_name=filename, mime='text/csv')
    else:
        st.caption('No hay mediciones guardadas.')
    st.caption('La lectura de Supabase es de solo consulta. Para recibir datos reales faltan configurar el receptor ESP32 y el envío seguro a la nube.')


if refresh:
    @st.fragment(run_every='5s')
    def live_panel():
        render()
else:
    def live_panel():
        render()

live_panel()

