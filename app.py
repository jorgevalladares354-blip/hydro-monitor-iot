import streamlit as st
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime, timedelta

st.set_page_config(page_title='Hydro Monitor IoT', page_icon='💧', layout='wide')
st.markdown('''<style>.block-container{padding-top:1.7rem;max-width:1350px} [data-testid="stMetric"]{background:#10263c;border:1px solid #255270;border-radius:15px;padding:18px} [data-testid="stMetricLabel"]{color:#a7c8dd} h1,h2,h3{letter-spacing:-.02em}</style>''', unsafe_allow_html=True)
st.title('💧 HYDRO MONITOR IoT')
st.caption('Panel de monitoreo hidráulico · ESP32 · Caudalímetro · LoRa (pendiente)')
mode = st.sidebar.radio('Fuente de datos', ['Demostración', 'Archivo local del ESP32'], index=0)
st.sidebar.caption('Los datos simulados no representan ensayos reales.')
refresh = st.sidebar.checkbox('Actualizar automáticamente cada 5 segundos', value=False)
if refresh:
    import time
    @st.fragment(run_every='5s')
    def live_panel():
        render()
else:
    def live_panel():
        render()

def load_data():
    if mode == 'Demostración':
        ts = pd.date_range(end=datetime.now(), periods=60, freq='min')
        q = np.maximum(0, 2.4 + .35*np.sin(np.linspace(0,9,60)) + .1*np.cos(np.linspace(0,25,60)))
        return pd.DataFrame({'fecha_hora':ts,'caudal_l_min':q.round(3)}), True
    path = Path(__file__).resolve().parent / 'datos' / 'mediciones.csv'
    if not path.exists():
        return pd.DataFrame(columns=['fecha_hora','caudal_l_min']), False
    try:
        df = pd.read_csv(path)
        if not {'fecha_hora','caudal_l_min'}.issubset(df.columns):
            st.error('El CSV debe contener fecha_hora y caudal_l_min.')
            return pd.DataFrame(columns=['fecha_hora','caudal_l_min']), False
        df['fecha_hora'] = pd.to_datetime(df['fecha_hora'],errors='coerce')
        df['caudal_l_min'] = pd.to_numeric(df['caudal_l_min'],errors='coerce')
        df = df.dropna(subset=['fecha_hora','caudal_l_min']).sort_values('fecha_hora')
        return df, False
    except (OSError,ValueError,pd.errors.ParserError) as exc:
        st.error(f'No se pudo leer el historial: {exc}')
        return pd.DataFrame(columns=['fecha_hora','caudal_l_min']), False

def render():
    df, demo = load_data()
    if demo:
        st.warning('MODO DEMOSTRACIÓN · Datos simulados, NO mediciones del caudalímetro.')
    elif df.empty:
        st.info('SIN LECTURAS · Ejecuta receptor_esp32.py cuando el ESP32 esté conectado y transmitiendo.')
    if not df.empty:
        last = df.iloc[-1]
        age = (datetime.now() - last['fecha_hora'].to_pydatetime()).total_seconds()
        connected = not demo and -10 <= age <= 15
        flow = float(last['caudal_l_min'])
        # Integración trapezoidal sobre marcas de tiempo; solo si hay intervalos válidos.
        seconds = df['fecha_hora'].diff().dt.total_seconds()
        intervals = seconds.where((seconds>0)&(seconds<=120),0).fillna(0)
        volume = ((df['caudal_l_min'] + df['caudal_l_min'].shift(1).fillna(df['caudal_l_min']))/2 * intervals/60).sum()
        state = 'Demostración' if demo else ('Datos recientes' if connected else 'Sin señal reciente')
        last_time = last['fecha_hora'].strftime('%Y-%m-%d %H:%M:%S')
    else:
        flow = None; volume = None; state='Sin datos'; last_time='—'
    a,b,c,d = st.columns(4)
    a.metric('Caudal actual', f'{flow:.2f} L/min' if flow is not None else '—')
    b.metric('Volumen integrado', f'{volume:.2f} L' if volume is not None else '—')
    c.metric('Estado', state)
    d.metric('Registros', str(len(df)))
    st.caption(f'Última lectura: {last_time} · Volumen estimado por integración; intervalos mayores a 120 s se excluyen.')
    st.subheader('📈 Evolución del caudal')
    if not df.empty:
        st.line_chart(df.set_index('fecha_hora')['caudal_l_min'], y_label='L/min')
    else:
        st.info('El gráfico aparecerá cuando existan lecturas.')
    st.subheader('📋 Historial')
    if not df.empty:
        display = df.rename(columns={'fecha_hora':'Fecha y hora','caudal_l_min':'Caudal (L/min)'})
        st.dataframe(display.sort_values('Fecha y hora',ascending=False),use_container_width=True,hide_index=True)
        st.download_button('⬇ Descargar CSV',data=display.to_csv(index=False).encode('utf-8-sig'),file_name='hidro_demo.csv' if demo else 'hidro_mediciones.csv',mime='text/csv')
    else:
        st.caption('No hay mediciones guardadas.')
    st.caption('LoRa y publicación pública con datos en vivo requieren configurar un receptor y almacenamiento accesible por Internet.')

live_panel()
