import React, { useRef, useState, useEffect, useCallback } from 'react';
import axios from 'axios';
import {
  Camera, Sparkles, ShoppingBag, CheckCircle2, X,
  MessageCircle, Droplets, Check, Activity, Zap, Mail, ArrowRight,
  Smile, Lock, Clock, Star, History, ChevronRight, Share2, TrendingUp
} from 'lucide-react';

const API = 'https://moonbow-ai-782467635197.southamerica-west1.run.app';

const STEPS = [
  { label: 'Paso 1: Limpiador Oleoso',  terms: ['Aceite', 'Balsamo', 'Oil'],
    benefit: 'Disuelve impurezas y maquillaje sin resecar' },
  { label: 'Paso 2: Limpiador Acuoso',  terms: ['Limpiador', 'Gel', 'Foam', 'Espuma', 'Cleaner', 'Cleanser'],
    benefit: 'Limpieza profunda y equilibrio del pH' },
  { label: 'Paso 3: Tonico',            terms: ['Tonico', 'Toner'],
    benefit: 'Prepara la piel para absorber mejor los siguientes pasos' },
  { label: 'Paso 4: Serum',             terms: ['Serum', 'Suero', 'Ampolla'],
    benefit: 'Tratamiento concentrado para tu tipo de piel' },
  { label: 'Paso 5: Contorno de Ojos',  terms: ['Ojos', 'Eye', 'Contorno'],
    benefit: 'Reduce ojeras y lineas finas alrededor del ojo' },
  { label: 'Paso 6: Hidratante',        terms: ['Crema', 'Cream', 'Hidratante'],
    benefit: 'Sella la hidratacion y fortalece la barrera cutanea' },
  { label: 'Paso 7: Proteccion Solar',  terms: ['Solar', 'SPF', 'Sun'],
    benefit: 'Proteccion esencial contra UV y envejecimiento' }
];

function stepBenefit(step, skinTag) {
  const custom = {
    grasa: {
      'Paso 1: Limpiador Oleoso':  'Elimina el exceso de sebo sin irritar',
      'Paso 2: Limpiador Acuoso':  'Controla el brillo y limpia los poros',
      'Paso 3: Tonico':            'Regula la produccion de grasa',
      'Paso 4: Serum':             'Reduce poros y controla el sebo',
      'Paso 6: Hidratante':        'Hidrata sin obstruir poros',
    },
    seca: {
      'Paso 2: Limpiador Acuoso':  'Limpia sin eliminar el manto hidrolipidico',
      'Paso 4: Serum':             'Aporta hidratacion profunda en capas',
      'Paso 6: Hidratante':        'Nutricion intensa para pieles secas',
    },
    mixta: {
      'Paso 2: Limpiador Acuoso':  'Equilibra zona T grasa y mejillas secas',
      'Paso 4: Serum':             'Hidrata y controla brillo a la vez',
      'Paso 6: Hidratante':        'Textura ligera para equilibrar la piel',
    },
    sensible: {
      'Paso 2: Limpiador Acuoso':  'Formula suave sin fragancia ni alcohol',
      'Paso 4: Serum':             'Calma rojeces y refuerza la barrera',
      'Paso 6: Hidratante':        'Calmante e hipoalergenico',
    }
  };
  return custom[skinTag]?.[step.label] || step.benefit;
}

// MEJORA 2: Resultados esperados por tipo de piel
function expectedResults(skinTag) {
  const results = {
    grasa:    ['Menos brillo en 7 dias', 'Poros menos visibles en 2 semanas', 'Piel mas mate y uniforme'],
    seca:     ['Menos tension al despertar en 5 dias', 'Piel mas suave en 1 semana', 'Hidratacion duradera en 2 semanas'],
    mixta:    ['Zona T controlada en 7 dias', 'Mejillas mas hidratadas en 10 dias', 'Piel mas equilibrada en 2 semanas'],
    sensible: ['Menos rojeces en 5 dias', 'Piel mas calmada en 1 semana', 'Barrera cutanea reforzada en 2 semanas'],
  };
  return results[skinTag] || ['Mejora visible en 7 dias', 'Piel mas saludable en 2 semanas', 'Resultados duraderos'];
}

// MEJORA 4: Score de piel — base real desde elasticidad
function skinScore(result) {
  if (!result) return 55;
  const e = parseInt(result.elasticidad || 65);
  const h = (result.hidratacion || '').toLowerCase();
  let hAdj = h === 'optima' ? 5 : h === 'baja' ? -8 : 0;
  const s = (result.sensibilidad || '').toLowerCase();
  let sAdj = s === 'baja' ? 3 : s === 'alta' ? -6 : 0;
  const raw = Math.round(e * 0.80 + hAdj + sAdj);
  return Math.min(Math.max(raw, 30), 88);
}

function scoreLabel(score) {
  if (score >= 90) return { text: 'Excelente', color: '#22c55e' };
  if (score >= 75) return { text: 'Buena', color: '#84cc16' };
  if (score >= 60) return { text: 'Regular', color: '#f59e0b' };
  return { text: 'Necesita atencion', color: '#ff85a2' };
}

// MEJORA 5: Comparar con analisis anterior
function compareWithLast(current, last) {
  if (!last) return null;
  const messages = [];
  const ch = (current.hidratacion || '').toLowerCase();
  const lh = (last.hidratacion || '').toLowerCase();
  const levels = { baja: 0, media: 1, optima: 2 };
  if (levels[ch] > levels[lh]) messages.push('Tu hidratacion mejoro');
  if (levels[ch] < levels[lh]) messages.push('Tu hidratacion bajo un poco');
  const ce = parseInt(current.elasticidad || 70);
  const le = parseInt(last.elasticidad || 70);
  if (ce > le + 3) messages.push(`Mejor firmeza (+${ce - le}%)`);
  if (ce < le - 3) messages.push(`Firmeza bajo (${ce - le}%)`);
  const cs = (current.sensibilidad || '').toLowerCase();
  const ls = (last.sensibilidad || '').toLowerCase();
  const slevels = { alta: 0, media: 1, baja: 2 };
  if (slevels[cs] > slevels[ls]) messages.push('Menos sensible que antes');
  return messages.length > 0 ? messages : null;
}

const LOADING_MESSAGES = [
  'Detectando nivel de hidratacion...',
  'Analizando textura de la piel...',
  'Evaluando zona T y poros...',
  'Estimando edad de la piel...',
  'Calculando tu score de piel...',
  'Preparando tu rutina personalizada...'
];

function humanizeHydration(val) {
  if (!val) return 'Normal';
  const v = val.toLowerCase();
  if (v === 'baja')   return 'Necesita mas agua';
  if (v === 'media')  return 'Hidratacion moderada';
  if (v === 'optima') return 'Bien hidratada';
  return val;
}
function humanizeElasticity(val) {
  if (!val) return 'Normal';
  const n = parseInt(val);
  if (n >= 85) return 'Excelente firmeza';
  if (n >= 70) return 'Buena firmeza';
  if (n >= 55) return 'Firmeza moderada';
  return 'Necesita nutricion';
}
function humanizeSensitivity(val) {
  if (!val) return 'Normal';
  const v = val.toLowerCase();
  if (v === 'baja')  return 'Piel resistente';
  if (v === 'media') return 'Algo reactiva';
  if (v === 'alta')  return 'Muy sensible';
  return val;
}

function matchesStep(title, terms) {
  return terms.some(t => title.toLowerCase().includes(t.toLowerCase()));
}

function getVisibleProducts(rawProducts) {
  const seen = new Set();
  const visible = [];
  for (const step of STEPS) {
    const prod = rawProducts.find(p => matchesStep(p.title, step.terms));
    if (prod && !seen.has(prod.title)) {
      seen.add(prod.title);
      visible.push(prod);
    }
  }
  return visible;
}

function saveHistory(result, products) {
  try {
    const history = JSON.parse(localStorage.getItem('moonbow_history') || '[]');
    history.unshift({
      date: new Date().toISOString(),
      tipo_piel: result.tipo_piel,
      tipo_piel_tag: result.tipo_piel_tag,
      analisis: result.analisis,
      hidratacion: result.hidratacion,
      elasticidad: result.elasticidad,
      sensibilidad: result.sensibilidad,
      edad_piel: result.edad_piel,
      products: products.map(p => ({ title: p.title, price: p.price, variant_id: p.variant_id }))
    });
    localStorage.setItem('moonbow_history', JSON.stringify(history.slice(0, 5)));
  } catch (e) { console.error(e); }
}

function loadHistory() {
  try { return JSON.parse(localStorage.getItem('moonbow_history') || '[]'); }
  catch { return []; }
}

function formatDate(iso) {
  return new Date(iso).toLocaleDateString('es-CL', { day: 'numeric', month: 'short', year: 'numeric' });
}

export default function App() {
  const videoRef = useRef(null);
  const canvasRef = useRef(null);

  const [image, setImage]               = useState(null);
  const [loading, setLoading]           = useState(false);
  const [loadingMsg, setLoadingMsg]     = useState(LOADING_MESSAGES[0]);
  const [result, setResult]             = useState(null);
  const [products, setProducts]         = useState([]);
  const [selectedProducts, setSelectedProducts] = useState([]);
  const [error, setError]               = useState(null);
  const [stream, setStream]             = useState(null);
  const [email, setEmail]               = useState('');
  const [emailLoading, setEmailLoading] = useState(false);
  const [emailDone, setEmailDone]       = useState(false);
  const [emailError, setEmailError]     = useState('');
  const [showModal, setShowModal]       = useState(false);
  const [showHistory, setShowHistory]   = useState(false);
  const [history, setHistory]           = useState([]);
  const [improvements, setImprovements] = useState(null);

  useEffect(() => { setHistory(loadHistory()); }, []);

  const startCamera = async () => {
    setError(null);
    if (stream) stream.getTracks().forEach(t => t.stop());
    try {
      const mediaStream = await navigator.mediaDevices.getUserMedia({
        video: { width: { ideal: 1080 }, height: { ideal: 1080 }, facingMode: 'user' },
        audio: false
      });
      if (videoRef.current) {
        videoRef.current.srcObject = mediaStream;
        videoRef.current.onloadedmetadata = () => setStream(mediaStream);
      }
    } catch { setError('No pudimos conectar con la camara.'); }
  };

  useEffect(() => {
    if (!image) startCamera();
    return () => { if (stream) stream.getTracks().forEach(t => t.stop()); };
  }, [image]);

  useEffect(() => {
    if (!loading) return;
    let idx = 0;
    const interval = setInterval(() => {
      idx = (idx + 1) % LOADING_MESSAGES.length;
      setLoadingMsg(LOADING_MESSAGES[idx]);
    }, 1800);
    return () => clearInterval(interval);
  }, [loading]);

  const capture = useCallback(async () => {
    if (!videoRef.current || !canvasRef.current) return;
    const canvas = canvasRef.current;
    canvas.width  = videoRef.current.videoWidth;
    canvas.height = videoRef.current.videoHeight;
    canvas.getContext('2d').drawImage(videoRef.current, 0, 0);
    // MEJORA 8: calidad bajada a 0.6 para menor peso
    const capturedImage = canvas.toDataURL('image/jpeg', 0.6);
    setImage(capturedImage);
    if (stream) stream.getTracks().forEach(t => t.stop());
    await runAnalysis(capturedImage);
  }, [stream]);

  const runAnalysis = async (imageData) => {
    setLoading(true);
    setLoadingMsg(LOADING_MESSAGES[0]);
    setError(null);
  
    try {
      const blob = await (await fetch(imageData)).blob();
      const formData = new FormData();
      formData.append('file', blob, 'face.jpg');
  
      const res = await axios.post(`${API}/analyze`, formData);
  
      const data = res.data?.result;
      if (!data) throw new Error('Respuesta invalida');
  
      setResult(data);
  
      const rawProducts = res.data?.products || [];
      setProducts(rawProducts);
  
      const visible = getVisibleProducts(rawProducts);
      setSelectedProducts(visible);
  
      saveHistory(data, visible);
      setHistory(loadHistory());
  
    } catch (err) {
      console.error(err);
      setError('Error al analizar. Intenta nuevamente.');
    } finally {
      setLoading(false);
    }
  };



  const toggleProduct = (product) => {
    setSelectedProducts(prev =>
      prev.find(p => p.title === product.title)
        ? prev.filter(p => p.title !== product.title)
        : [...prev, product]
    );
  };

  const handleEmailSubmit = async () => {
    if (!email || !email.includes('@')) { setEmailError('Ingresa un email valido'); return; }
    setEmailLoading(true);
    setEmailError('');
    try {
      await axios.post(`${API}/subscribe`, {
        email,
        skin_type:       result?.tipo_piel        || '',
        skin_tag:        result?.tipo_piel_tag     || '',
        products:        selectedProducts,
        // Analisis completo para personalizacion de emails
        analisis:        result?.analisis          || '',
        hidratacion:     result?.hidratacion       || '',
        sensibilidad:    result?.sensibilidad      || '',
        elasticidad:     parseInt(result?.elasticidad) || 0,
        edad_piel:       parseInt(result?.edad_piel)   || 0,
        puntos_clave:    result?.puntos_clave      || [],
        rutina_sugerida: result?.rutina_sugerida   || '',
        score:           score || 0,
      });
      setEmailDone(true);
      setTimeout(() => { openCartUrl(); setShowModal(false); }, 1500);
    } catch (err) {
      console.error(err);
      openCartUrl();
      setShowModal(false);
    } finally { setEmailLoading(false); }
  };

  const openCartUrl = () => {
    const valid = selectedProducts.filter(p => p.variant_id);
    if (!valid.length) return;
    window.open(`https://moonbow.cl/cart/${valid.map(p => `${p.variant_id}:1`).join(',')}`, '_blank');
  };

  // MEJORA 6: Compartir resultado
  const shareResult = () => {
    const score = skinScore(result);
    const text = `Probe esta IA de skincare y descubri que tengo ${result?.tipo_piel} con un score de ${score}/100! Mi rutina personalizada esta lista en Moonbow.cl`;
    const whatsappUrl = `https://wa.me/?text=${encodeURIComponent(text + ' -> https://moonbow.cl')}`;
    window.open(whatsappUrl, '_blank');
  };

  const openWhatsApp = () => {
    const msg = `Hola Moonbow! Acabo de hacer mi analisis de piel IA.\n\nResultado: ${result?.tipo_piel}\n${result?.analisis}\n\nProductos recomendados:\n${selectedProducts.map(p => `- ${p.title}`).join('\n')}`;
    window.open(`https://wa.me/+56912345678?text=${encodeURIComponent(msg)}`, '_blank');
  };

  const totalPrice = selectedProducts.reduce((acc, p) => acc + parseFloat(p.price || 0), 0);
  const score = result ? skinScore(result) : 0;
  const scoreInfo = scoreLabel(score);
  const targetScore = Math.min(score + 15, 99);

  const badges = result ? [
    { icon: <Droplets size={15} color="#ff85a2" />, label: 'Hidratacion',  value: humanizeHydration(result.hidratacion) },
    { icon: <Activity size={15} color="#ff85a2" />, label: 'Firmeza',      value: humanizeElasticity(result.elasticidad) },
    { icon: <Zap      size={15} color="#ff85a2" />, label: 'Sensibilidad', value: humanizeSensitivity(result.sensibilidad) },
    { icon: <Smile    size={15} color="#ff85a2" />, label: 'Edad Piel',    value: result.edad_piel ? `${result.edad_piel} anos` : '--' }
  ] : [];

  return (
    <div style={{ fontFamily: "'Plus Jakarta Sans', sans-serif", maxWidth: '480px', margin: '0 auto', padding: '20px', backgroundColor: '#fffcfd', minHeight: '100vh', color: '#1a1a1a', paddingBottom: '140px' }}>

      {/* Header — MEJORA 9: copy mejorado */}
      <header style={{ textAlign: 'center', marginBottom: '20px', position: 'relative' }}>
        <div style={{ display: 'inline-block', padding: '6px 14px', background: '#fff', borderRadius: '100px', boxShadow: '0 4px 15px rgba(255,133,162,0.12)', marginBottom: '12px' }}>
          <span style={{ color: '#ff85a2', fontWeight: '800', fontSize: '11px', letterSpacing: '1.5px' }}>MOONBOW AI EXPERIENCE</span>
        </div>
        <h1 style={{ fontSize: '21px', fontWeight: '800', letterSpacing: '-0.5px', margin: 0, lineHeight: '1.3' }}>
          Tu piel, entendida por IA
        </h1>
        <p style={{ fontSize: '13px', color: '#bbb', margin: '6px 0 0' }}>Diagnostico real, no adivinanzas</p>

        {history.length > 0 && !image && (
          <button onClick={() => setShowHistory(true)}
            style={{ position: 'absolute', right: 0, top: '50%', transform: 'translateY(-50%)', background: '#fff5f7', border: '1px solid #ffdae3', borderRadius: '12px', padding: '8px 10px', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '5px' }}>
            <History size={14} color="#ff85a2" />
            <span style={{ fontSize: '11px', fontWeight: '700', color: '#ff85a2' }}>Mis analisis</span>
          </button>
        )}
      </header>

      {/* Trust bar */}
      {!image && (
        <div style={{ display: 'flex', justifyContent: 'center', gap: '6px', marginBottom: '20px', flexWrap: 'wrap' }}>
          {[
            { icon: <Lock  size={11} color="#ff85a2" />, text: 'No guardamos tu foto' },
            { icon: <Clock size={11} color="#ff85a2" />, text: 'Resultado en 5 segundos' },
            { icon: <Star  size={11} color="#ff85a2" />, text: 'Recomendado por expertas' }
          ].map((item, i) => (
            <div key={i} style={{ display: 'flex', alignItems: 'center', gap: '5px', background: '#fff5f7', padding: '6px 11px', borderRadius: '100px', border: '1px solid #ffdae3' }}>
              {item.icon}
              <span style={{ fontSize: '11px', fontWeight: '700', color: '#ff85a2' }}>{item.text}</span>
            </div>
          ))}
        </div>
      )}

      {/* Camara */}
      {!image && (
        <div style={{ textAlign: 'center' }}>
          <div style={{ borderRadius: '36px', overflow: 'hidden', backgroundColor: '#000', aspectRatio: '1/1', boxShadow: '0 20px 50px rgba(255,133,162,0.15)', position: 'relative' }}>
            <video ref={videoRef} autoPlay playsInline style={{ width: '100%', height: '100%', objectFit: 'cover', transform: 'scaleX(-1)' }} />

            {/* Overlay guia de rostro */}
            <div style={{ position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', pointerEvents: 'none' }}>
              <svg viewBox="0 0 300 360" style={{ width: '75%', maxWidth: '270px', filter: 'drop-shadow(0 0 12px rgba(255,133,162,0.5))' }}>
                <defs>
                  <mask id="faceMask">
                    <rect width="300" height="360" fill="white" />
                    <ellipse cx="150" cy="175" rx="108" ry="138" fill="black" />
                  </mask>
                </defs>
                <rect width="300" height="360" fill="rgba(0,0,0,0.42)" mask="url(#faceMask)" />
                <ellipse cx="150" cy="175" rx="108" ry="138" fill="none" stroke="#ff85a2" strokeWidth="2.5" strokeDasharray="9 5" opacity="0.9" />
                {/* Marcas de alineacion */}
                <line x1="42" y1="175" x2="18" y2="175" stroke="#ff85a2" strokeWidth="2" opacity="0.6" />
                <line x1="258" y1="175" x2="282" y2="175" stroke="#ff85a2" strokeWidth="2" opacity="0.6" />
                <line x1="150" y1="37" x2="150" y2="15" stroke="#ff85a2" strokeWidth="2" opacity="0.6" />
                <line x1="150" y1="313" x2="150" y2="338" stroke="#ff85a2" strokeWidth="2" opacity="0.6" />
              </svg>
              <div style={{ marginTop: '10px', background: 'rgba(0,0,0,0.6)', backdropFilter: 'blur(8px)', borderRadius: '100px', padding: '8px 20px', border: '1px solid rgba(255,133,162,0.45)' }}>
                <span style={{ color: 'white', fontSize: '13px', fontWeight: '700' }}>👤 Pon aquí tu rostro</span>
              </div>
            </div>
          </div>
          {error && <p style={{ color: '#ff4444', marginTop: '12px', fontSize: '14px' }}>{error}</p>}
          <p style={{ color: '#bbb', fontSize: '13px', margin: '14px 0 8px' }}>Buena iluminacion frontal, sin lentes ni gorro</p>
          <button onClick={capture} style={{ width: '100%', backgroundColor: '#1a1a1a', color: 'white', padding: '20px', borderRadius: '22px', fontSize: '16px', fontWeight: '800', border: 'none', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '12px' }}>
            <Camera size={22} /> Escanear mi Piel
          </button>
        </div>
      )}

      {/* Resultados */}
      {image && (
        <div style={{ animation: 'fadeIn 0.5s ease' }}>
          <div style={{ borderRadius: '36px', overflow: 'hidden', border: '5px solid white', boxShadow: '0 15px 35px rgba(0,0,0,0.05)', aspectRatio: '1.2/1', marginBottom: '14px' }}>
            <img src={image} alt="Captura" style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
          </div>

          {!loading && (
            <button onClick={() => { setImage(null); setResult(null); setProducts([]); setSelectedProducts([]); setError(null); setEmailDone(false); setImprovements(null); }}
              style={{ width: '100%', background: '#f5f5f5', color: '#777', border: 'none', padding: '11px', borderRadius: '14px', fontWeight: '600', cursor: 'pointer', marginBottom: '16px', fontSize: '13px' }}>
              Tomar otra foto
            </button>
          )}

          {loading && (
            <div style={{ textAlign: 'center', padding: '36px 0' }}>
              <div style={{ width: '44px', height: '44px', border: '3px solid #ffdae3', borderTop: '3px solid #ff85a2', borderRadius: '50%', margin: '0 auto 18px', animation: 'spin 0.8s linear infinite' }} />
              <p key={loadingMsg} style={{ color: '#ff85a2', fontWeight: '700', fontSize: '15px', margin: '0 0 6px', animation: 'fadeIn 0.4s ease', minHeight: '24px' }}>{loadingMsg}</p>
              <div style={{ display: 'flex', justifyContent: 'center', gap: '4px', marginTop: '12px' }}>
                {LOADING_MESSAGES.map((msg, i) => (
                  <div key={i} style={{ width: '6px', height: '6px', borderRadius: '50%', background: loadingMsg === msg ? '#ff85a2' : '#ffdae3', transition: 'background 0.3s' }} />
                ))}
              </div>
            </div>
          )}

          {error && !loading && (
            <div style={{ textAlign: 'center', padding: '16px' }}>
              <p style={{ color: '#ff4444', marginBottom: '14px', fontSize: '14px' }}>{error}</p>
              <button onClick={() => runAnalysis(image)} style={{ background: '#ff85a2', color: 'white', border: 'none', padding: '12px 24px', borderRadius: '18px', fontWeight: '700', cursor: 'pointer' }}>Reintentar</button>
            </div>
          )}

          {result && !loading && (
            <div>

              {/* MEJORA 5: Banner de mejora vs analisis anterior */}
              {improvements && improvements.length > 0 && (
                <div style={{ background: 'linear-gradient(135deg, #f0fdf4 0%, #dcfce7 100%)', border: '1.5px solid #86efac', borderRadius: '20px', padding: '14px 18px', marginBottom: '18px', display: 'flex', alignItems: 'center', gap: '10px', animation: 'fadeIn 0.5s ease' }}>
                  <TrendingUp size={18} color="#22c55e" style={{ flexShrink: 0 }} />
                  <div>
                    <p style={{ margin: 0, fontWeight: '800', fontSize: '13px', color: '#15803d' }}>Tu piel mejoro desde la ultima vez</p>
                    <p style={{ margin: '2px 0 0', fontSize: '12px', color: '#4ade80' }}>{improvements.join(' · ')}</p>
                  </div>
                </div>
              )}

              {/* MEJORA 4: Score de piel */}
              <div style={{ background: 'white', borderRadius: '24px', padding: '20px', marginBottom: '18px', border: '1px solid #f0f0f0' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
                  <div>
                    <p style={{ margin: 0, fontSize: '12px', color: '#bbb', fontWeight: '700', textTransform: 'uppercase', letterSpacing: '0.5px' }}>Score de tu piel</p>
                    <div style={{ display: 'flex', alignItems: 'baseline', gap: '6px', marginTop: '4px' }}>
                      <span style={{ fontSize: '32px', fontWeight: '900', color: scoreInfo.color }}>{score}</span>
                      <span style={{ fontSize: '16px', fontWeight: '600', color: '#ccc' }}>/100</span>
                      <span style={{ fontSize: '13px', fontWeight: '800', color: scoreInfo.color, marginLeft: '4px' }}>{scoreInfo.text}</span>
                    </div>
                  </div>
                  <div style={{ textAlign: 'right' }}>
                    <p style={{ margin: 0, fontSize: '11px', color: '#bbb' }}>Meta con esta rutina</p>
                    <p style={{ margin: '2px 0 0', fontSize: '20px', fontWeight: '900', color: '#22c55e' }}>{targetScore}+</p>
                  </div>
                </div>
                {/* Barra de progreso */}
                <div style={{ background: '#f5f5f5', borderRadius: '100px', height: '8px', overflow: 'hidden' }}>
                  <div style={{ width: `${score}%`, height: '100%', background: `linear-gradient(90deg, #ff85a2, ${scoreInfo.color})`, borderRadius: '100px', transition: 'width 1s ease' }} />
                </div>
                <p style={{ margin: '8px 0 0', fontSize: '11px', color: '#bbb' }}>Siguiendo esta rutina puedes llegar a {targetScore}+ en 30 dias</p>
              </div>

              {/* Badges 2x2 */}
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px', marginBottom: '20px' }}>
                {badges.map((b, i) => (
                  <div key={i} style={{ background: 'white', padding: '14px 12px', borderRadius: '20px', border: '1px solid #f0f0f0', display: 'flex', alignItems: 'center', gap: '10px' }}>
                    <div style={{ width: '34px', height: '34px', background: '#fff5f7', borderRadius: '12px', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
                      {b.icon}
                    </div>
                    <div>
                      <p style={{ fontSize: '10px', fontWeight: '700', margin: '0 0 2px', color: '#ccc', textTransform: 'uppercase' }}>{b.label}</p>
                      <p style={{ fontSize: '12px', fontWeight: '800', margin: 0, lineHeight: '1.2' }}>{b.value}</p>
                    </div>
                  </div>
                ))}
              </div>

              {/* Diagnostico */}
              <div style={{ padding: '24px', background: 'white', borderRadius: '28px', marginBottom: '18px', border: '1px solid #f8f8f8' }}>
                <h3 style={{ margin: '0 0 10px', fontSize: '20px', fontWeight: '800', color: '#ff85a2' }}>{result.tipo_piel}</h3>
                <p style={{ fontSize: '14px', color: '#666', lineHeight: '1.6', margin: '0 0 16px' }}>{result.analisis}</p>
                {result.puntos_clave && (
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: '7px' }}>
                    {result.puntos_clave.map((pt, i) => (
                      <span key={i} style={{ background: '#fff5f7', color: '#ff85a2', padding: '5px 11px', borderRadius: '9px', fontSize: '12px', fontWeight: '700' }}>v {pt}</span>
                    ))}
                  </div>
                )}
              </div>

              {/* MEJORA 2: Resultados esperados */}
              <div style={{ background: '#f8fff8', border: '1.5px solid #bbf7d0', borderRadius: '22px', padding: '18px 20px', marginBottom: '20px' }}>
                <p style={{ margin: '0 0 12px', fontSize: '13px', fontWeight: '800', color: '#1a1a1a' }}>Si sigues esta rutina:</p>
                {expectedResults(result.tipo_piel_tag).map((r, i) => (
                  <div key={i} style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: i < 2 ? '8px' : 0 }}>
                    <div style={{ width: '18px', height: '18px', background: '#22c55e', borderRadius: '50%', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
                      <Check size={10} color="white" strokeWidth={3} />
                    </div>
                    <span style={{ fontSize: '13px', color: '#555', fontWeight: '600' }}>{r}</span>
                  </div>
                ))}
              </div>

              {/* Banner seleccion */}
              {selectedProducts.length > 0 && (
                <div style={{ padding: '14px 18px', background: '#fff5f7', borderRadius: '18px', border: '1.5px solid #ffdae3', marginBottom: '18px' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '4px' }}>
                    <Sparkles size={14} color="#ff85a2" />
                    <span style={{ fontSize: '13px', fontWeight: '800' }}>{selectedProducts.length} productos elegidos para tu {result.tipo_piel.toLowerCase()}</span>
                  </div>
                  <p style={{ margin: 0, fontSize: '12px', color: '#bbb' }}>Toca un producto para quitarlo de tu rutina.</p>
                </div>
              )}

              {/* Lista productos con beneficio personalizado */}
              {products.length > 0 ? (
                <div style={{ marginBottom: '20px' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '14px' }}>
                    <h4 style={{ fontSize: '16px', fontWeight: '800', margin: 0 }}>Tu Rutina Personalizada</h4>
                    <span style={{ fontSize: '11px', color: '#ccc', fontWeight: '600' }}>Toca para editar</span>
                  </div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                    {STEPS.map((step, idx) => {
                      const prod = products.find(p => matchesStep(p.title, step.terms));
                      if (!prod) return null;
                      const isSel = !!selectedProducts.find(s => s.title === prod.title);
                      const benefit = stepBenefit(step, result.tipo_piel_tag);
                      return (
                        <div key={idx} onClick={() => toggleProduct(prod)} style={{
                          display: 'flex', gap: '13px', padding: '14px',
                          background: isSel ? '#fffcfd' : '#fafafa',
                          borderRadius: '20px',
                          border: `2px solid ${isSel ? '#ff85a2' : '#efefef'}`,
                          cursor: 'pointer', transition: 'all 0.15s ease',
                          opacity: isSel ? 1 : 0.45
                        }}>
                          <div style={{ position: 'relative', flexShrink: 0 }}>
                            {prod.image
                              ? <img src={prod.image} alt={prod.title} style={{ width: '60px', height: '60px', borderRadius: '14px', objectFit: 'cover' }} />
                              : <div style={{ width: '60px', height: '60px', borderRadius: '14px', background: '#f0f0f0' }} />
                            }
                            {isSel && (
                              <div style={{ position: 'absolute', top: '-5px', right: '-5px', background: '#ff85a2', borderRadius: '50%', width: '19px', height: '19px', display: 'flex', alignItems: 'center', justifyContent: 'center', border: '2px solid white' }}>
                                <Check size={10} color="white" strokeWidth={4} />
                              </div>
                            )}
                          </div>
                          <div style={{ flex: 1, minWidth: 0 }}>
                            <p style={{ fontSize: '9px', fontWeight: '800', color: '#ff85a2', margin: '0 0 3px', textTransform: 'uppercase', letterSpacing: '0.3px' }}>{step.label}</p>
                            <p style={{ fontSize: '12px', fontWeight: '700', margin: '0 0 3px', lineHeight: '1.2', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{prod.title}</p>
                            <p style={{ fontSize: '11px', color: '#999', margin: '0 0 5px', lineHeight: '1.3' }}>{benefit}</p>
                            <p style={{ fontSize: '14px', fontWeight: '900', margin: 0 }}>${Math.round(parseFloat(prod.price)).toLocaleString('es-CL')}</p>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              ) : (
                <div style={{ textAlign: 'center', padding: '28px', background: '#f9f9f9', borderRadius: '20px', marginBottom: '20px' }}>
                  <p style={{ color: '#bbb', margin: 0, fontSize: '14px' }}>No se encontraron productos para tu tipo de piel.</p>
                </div>
              )}

              {/* MEJORA 6: Boton compartir */}
              <button onClick={shareResult}
                style={{ width: '100%', background: 'white', color: '#1a1a1a', border: '1.5px solid #eee', padding: '14px', borderRadius: '18px', fontWeight: '700', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '9px', fontSize: '14px', marginBottom: '12px' }}>
                <Share2 size={16} color="#ff85a2" /> Compartir mi resultado
              </button>

              {/* WhatsApp CTA fuerte */}
              <div style={{ background: 'linear-gradient(135deg, #f0fdf4 0%, #fff 100%)', border: '1.5px solid #bbf7d0', borderRadius: '24px', padding: '20px', marginBottom: '16px' }}>
                <p style={{ fontSize: '15px', fontWeight: '800', margin: '0 0 6px', color: '#1a1a1a' }}>
                  Quieres que una experta revise tu analisis?
                </p>
                <p style={{ fontSize: '12px', color: '#888', margin: '0 0 14px', lineHeight: '1.5' }}>
                  Nuestras especialistas K-Beauty pueden orientarte sobre tu rutina ideal sin costo.
                </p>
                <button onClick={openWhatsApp} style={{ width: '100%', background: '#25D366', color: 'white', border: 'none', padding: '14px', borderRadius: '16px', fontWeight: '800', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '9px', fontSize: '14px' }}>
                  <MessageCircle size={17} /> Hablar con una experta ahora
                </button>
              </div>

            </div>
          )}
        </div>
      )}

      {/* MEJORA 1: Boton flotante con urgencia */}
      {selectedProducts.length > 0 && result && !loading && (
        <div style={{ position: 'fixed', bottom: '20px', left: '20px', right: '20px', zIndex: 100 }}>
          <button onClick={() => setShowModal(true)}
            style={{ width: '100%', background: '#1a1a1a', color: 'white', border: 'none', padding: '16px 22px', borderRadius: '26px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', boxShadow: '0 15px 40px rgba(0,0,0,0.25)', cursor: 'pointer' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '11px' }}>
              <ShoppingBag size={19} color="#ff85a2" />
              <div style={{ textAlign: 'left' }}>
                {/* MEJORA 1: Copy de urgencia */}
                <p style={{ margin: 0, fontWeight: '800', fontSize: '14px' }}>Empieza a mejorar tu piel hoy</p>
                <p style={{ margin: 0, fontSize: '11px', color: '#ff85a2' }}>Resultados visibles en 7-14 dias</p>
              </div>
            </div>
            <span style={{ fontWeight: '900', fontSize: '16px' }}>${Math.round(totalPrice).toLocaleString('es-CL')}</span>
          </button>
        </div>
      )}

      {/* Modal con mejor copy de email */}
      {showModal && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', backdropFilter: 'blur(8px)', zIndex: 200, display: 'flex', alignItems: 'flex-end', justifyContent: 'center' }}>
          <div style={{ background: 'white', borderRadius: '36px 36px 0 0', padding: '32px 24px 44px', width: '100%', maxWidth: '480px', animation: 'slideUp 0.3s ease', position: 'relative' }}>

            <button onClick={() => { setShowModal(false); setEmailDone(false); }}
              style={{ position: 'absolute', top: '20px', right: '20px', background: '#f5f5f5', border: 'none', borderRadius: '50%', width: '34px', height: '34px', display: 'flex', alignItems: 'center', justifyContent: 'center', cursor: 'pointer' }}>
              <X size={15} />
            </button>

            {emailDone ? (
              <div style={{ textAlign: 'center', padding: '24px 0' }}>
                <div style={{ width: '68px', height: '68px', background: '#fff5f7', borderRadius: '26px', display: 'flex', alignItems: 'center', justifyContent: 'center', margin: '0 auto 18px' }}>
                  <CheckCircle2 size={34} color="#ff85a2" />
                </div>
                <h3 style={{ fontSize: '19px', fontWeight: '800', margin: '0 0 8px' }}>Listo! Redirigiendo...</h3>
                <p style={{ color: '#bbb', fontSize: '13px', margin: 0 }}>Te enviamos tu diagnostico completo por email.</p>
              </div>
            ) : (
              <>
                <h3 style={{ fontSize: '17px', fontWeight: '800', margin: '0 0 4px' }}>Tu Rutina para {result?.tipo_piel}</h3>
                <p style={{ fontSize: '12px', color: '#999', margin: '0 0 18px' }}>{selectedProducts.length} productos personalizados</p>

                <div style={{ borderTop: '1px solid #f5f5f5', borderBottom: '1px solid #f5f5f5', padding: '12px 0', marginBottom: '18px' }}>
                  {selectedProducts.map((p, i) => (
                    <div key={i} style={{ display: 'flex', justifyContent: 'space-between', padding: '6px 0', fontSize: '12px' }}>
                      <span style={{ color: '#555', flex: 1, marginRight: '8px', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{p.title}</span>
                      <span style={{ fontWeight: '700', flexShrink: 0 }}>${Math.round(parseFloat(p.price)).toLocaleString('es-CL')}</span>
                    </div>
                  ))}
                  <div style={{ display: 'flex', justifyContent: 'space-between', padding: '10px 0 0', fontWeight: '900', fontSize: '14px', borderTop: '1px solid #f5f5f5', marginTop: '6px' }}>
                    <span>Total</span>
                    <span style={{ color: '#ff85a2' }}>${Math.round(totalPrice).toLocaleString('es-CL')}</span>
                  </div>
                </div>

                {/* MEJORA 7: Email con valor extra real */}
                <div style={{ background: '#fff5f7', borderRadius: '20px', padding: '18px', marginBottom: '14px' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '7px', marginBottom: '8px' }}>
                    <Mail size={14} color="#ff85a2" />
                    <span style={{ fontSize: '13px', fontWeight: '800' }}>Guarda tu analisis gratis</span>
                  </div>
                  {/* MEJORA 7: Lista de beneficios del email */}
                  {['Tu diagnostico completo + rutina manana y noche', 'Tips personalizados para tu ' + (result?.tipo_piel?.toLowerCase() || 'piel'), 'Seguimiento de tu evolucion mes a mes'].map((item, i) => (
                    <div key={i} style={{ display: 'flex', alignItems: 'flex-start', gap: '6px', marginBottom: '5px' }}>
                      <Check size={12} color="#ff85a2" style={{ marginTop: '2px', flexShrink: 0 }} />
                      <span style={{ fontSize: '11px', color: '#777', lineHeight: '1.4' }}>{item}</span>
                    </div>
                  ))}
                  <input
                    type="email"
                    value={email}
                    onChange={e => { setEmail(e.target.value); setEmailError(''); }}
                    placeholder="tu@email.com"
                    style={{ width: '100%', padding: '11px 14px', borderRadius: '12px', border: emailError ? '1.5px solid #ff4444' : '1.5px solid #ffdae3', fontSize: '14px', outline: 'none', background: 'white', boxSizing: 'border-box', marginTop: '10px' }}
                  />
                  {emailError && <p style={{ color: '#ff4444', fontSize: '11px', margin: '5px 0 0' }}>{emailError}</p>}
                </div>

                <button onClick={handleEmailSubmit} disabled={emailLoading}
                  style={{ width: '100%', background: '#ff85a2', color: 'white', border: 'none', padding: '17px', borderRadius: '20px', fontWeight: '800', fontSize: '15px', cursor: emailLoading ? 'not-allowed' : 'pointer', opacity: emailLoading ? 0.8 : 1, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '9px', marginBottom: '10px' }}>
                  {emailLoading ? 'Procesando...' : <><span>Ir al Carrito de Moonbow</span><ArrowRight size={17} /></>}
                </button>

                <button onClick={() => { openCartUrl(); setShowModal(false); }}
                  style={{ width: '100%', background: 'transparent', color: '#ccc', border: 'none', padding: '10px', cursor: 'pointer', fontSize: '12px', fontWeight: '600' }}>
                  Ir al carrito sin guardar mi analisis
                </button>
              </>
            )}
          </div>
        </div>
      )}

      {/* Modal historial */}
      {showHistory && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', backdropFilter: 'blur(8px)', zIndex: 200, display: 'flex', alignItems: 'flex-end', justifyContent: 'center' }}>
          <div style={{ background: 'white', borderRadius: '36px 36px 0 0', padding: '32px 24px 44px', width: '100%', maxWidth: '480px', animation: 'slideUp 0.3s ease', position: 'relative', maxHeight: '80vh', overflowY: 'auto' }}>
            <button onClick={() => setShowHistory(false)}
              style={{ position: 'absolute', top: '20px', right: '20px', background: '#f5f5f5', border: 'none', borderRadius: '50%', width: '34px', height: '34px', display: 'flex', alignItems: 'center', justifyContent: 'center', cursor: 'pointer' }}>
              <X size={15} />
            </button>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '20px' }}>
              <History size={20} color="#ff85a2" />
              <h3 style={{ fontSize: '18px', fontWeight: '800', margin: 0 }}>Mis Analisis Anteriores</h3>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
              {history.map((h, i) => (
                <div key={i} style={{ background: '#fafafa', borderRadius: '20px', padding: '16px', border: '1px solid #f0f0f0' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '8px' }}>
                    <div>
                      <p style={{ margin: 0, fontWeight: '800', fontSize: '15px', color: '#ff85a2' }}>{h.tipo_piel}</p>
                      <p style={{ margin: '2px 0 0', fontSize: '11px', color: '#bbb' }}>{formatDate(h.date)}</p>
                    </div>
                    <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap', justifyContent: 'flex-end' }}>
                      {h.hidratacion && <span style={{ fontSize: '10px', background: '#fff5f7', color: '#ff85a2', padding: '3px 8px', borderRadius: '8px', fontWeight: '700' }}>{h.hidratacion}</span>}
                      {h.edad_piel && <span style={{ fontSize: '10px', background: '#f5f5f5', color: '#888', padding: '3px 8px', borderRadius: '8px', fontWeight: '700' }}>{h.edad_piel} anos</span>}
                    </div>
                  </div>
                  <p style={{ margin: '0 0 10px', fontSize: '12px', color: '#777', lineHeight: '1.5' }}>{h.analisis}</p>
                  {h.products?.length > 0 && (
                    <div>
                      <p style={{ margin: '0 0 6px', fontSize: '11px', fontWeight: '700', color: '#bbb', textTransform: 'uppercase' }}>{h.products.length} productos recomendados</p>
                      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '5px' }}>
                        {h.products.slice(0, 3).map((p, j) => (
                          <span key={j} style={{ fontSize: '11px', background: 'white', border: '1px solid #eee', padding: '3px 8px', borderRadius: '8px', color: '#555' }}>{p.title.split(' ').slice(0, 3).join(' ')}</span>
                        ))}
                        {h.products.length > 3 && <span style={{ fontSize: '11px', color: '#bbb', padding: '3px 0' }}>+{h.products.length - 3} mas</span>}
                      </div>
                    </div>
                  )}
                  {h.products?.some(p => p.variant_id) && (
                    <button
                      onClick={() => {
                        const valid = h.products.filter(p => p.variant_id);
                        window.open(`https://moonbow.cl/cart/${valid.map(p => `${p.variant_id}:1`).join(',')}`, '_blank');
                      }}
                      style={{ marginTop: '12px', width: '100%', background: '#1a1a1a', color: 'white', border: 'none', padding: '11px', borderRadius: '14px', fontWeight: '700', cursor: 'pointer', fontSize: '12px', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px' }}>
                      Repetir esta rutina <ChevronRight size={13} />
                    </button>
                  )}
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      <canvas ref={canvasRef} style={{ display: 'none' }} />
      <style dangerouslySetInnerHTML={{ __html: `
        @keyframes fadeIn  { from { opacity:0; transform:translateY(10px); } to { opacity:1; transform:translateY(0); } }
        @keyframes slideUp { from { transform:translateY(100%); } to { transform:translateY(0); } }
        @keyframes spin    { from { transform:rotate(0deg); } to { transform:rotate(360deg); } }
        body { margin:0; background:#fffcfd; overflow-x:hidden; }
        input:focus { border-color:#ff85a2 !important; box-shadow:0 0 0 3px rgba(255,133,162,0.15); }
      ` }} />
    </div>
  );
}