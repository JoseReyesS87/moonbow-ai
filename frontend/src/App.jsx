import React, { useRef, useState, useEffect, useCallback } from 'react';
import axios from 'axios';
import {
  Camera, Sparkles, ShoppingBag, CheckCircle2, X,
  MessageCircle, Droplets, Check, Activity, Zap, Mail, ArrowRight
} from 'lucide-react';

const API = 'http://127.0.0.1:8000';

const STEPS = [
  { label: 'Paso 1: Limpiador Oleoso',  terms: ['Aceite', 'Balsamo', 'Oil'] },
  { label: 'Paso 2: Limpiador Acuoso',  terms: ['Limpiador', 'Gel', 'Foam', 'Espuma', 'Cleaner', 'Cleanser'] },
  { label: 'Paso 3: Tonico',            terms: ['Tonico', 'Toner'] },
  { label: 'Paso 4: Serum',             terms: ['Serum', 'Suero', 'Ampolla'] },
  { label: 'Paso 5: Contorno de Ojos',  terms: ['Ojos', 'Eye', 'Contorno'] },
  { label: 'Paso 6: Hidratante',        terms: ['Crema', 'Cream', 'Hidratante'] },
  { label: 'Paso 7: Proteccion Solar',  terms: ['Solar', 'SPF', 'Sun'] }
];

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

export default function App() {
  const videoRef = useRef(null);
  const canvasRef = useRef(null);

  const [image, setImage]                   = useState(null);
  const [loading, setLoading]               = useState(false);
  const [result, setResult]                 = useState(null);
  const [products, setProducts]             = useState([]);
  const [selectedProducts, setSelectedProducts] = useState([]);
  const [error, setError]                   = useState(null);
  const [stream, setStream]                 = useState(null);
  const [email, setEmail]                   = useState('');
  const [emailLoading, setEmailLoading]     = useState(false);
  const [emailDone, setEmailDone]           = useState(false);
  const [emailError, setEmailError]         = useState('');
  const [showModal, setShowModal]           = useState(false);

  // --- Camara ---
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
    } catch {
      setError('No pudimos conectar con la camara.');
    }
  };

  useEffect(() => {
    if (!image) startCamera();
    return () => { if (stream) stream.getTracks().forEach(t => t.stop()); };
  }, [image]);

  // --- Analisis automatico al capturar ---
  const capture = useCallback(async () => {
    if (!videoRef.current || !canvasRef.current) return;
    const canvas = canvasRef.current;
    canvas.width  = videoRef.current.videoWidth;
    canvas.height = videoRef.current.videoHeight;
    canvas.getContext('2d').drawImage(videoRef.current, 0, 0);
    const capturedImage = canvas.toDataURL('image/jpeg', 0.9);
    setImage(capturedImage);
    if (stream) stream.getTracks().forEach(t => t.stop());
    await runAnalysis(capturedImage);
  }, [stream]);

  const runAnalysis = async (imageData) => {
    setLoading(true);
    setError(null);
    try {
      const blob = await (await fetch(imageData)).blob();
      const formData = new FormData();
      formData.append('file', blob, 'face.jpg');

      const res = await axios.post(`${API}/analyze`, formData);
      const jsonMatch = (res.data.result || '').match(/\{[\s\S]*\}/);
      if (!jsonMatch) throw new Error('Respuesta invalida');

      const data = JSON.parse(jsonMatch[0]);
      setResult(data);

      const rawProducts = res.data.products || [];
      setProducts(rawProducts);

      // Preseleccionar solo los productos visibles en pantalla
      const visible = getVisibleProducts(rawProducts);
      setSelectedProducts(visible);
      console.log(`Productos visibles preseleccionados: ${visible.length}`);
    } catch (err) {
      console.error(err);
      setError('Error al analizar. Intenta nuevamente.');
    } finally {
      setLoading(false);
    }
  };

  // --- Seleccion ---
  const toggleProduct = (product) => {
    setSelectedProducts(prev =>
      prev.find(p => p.title === product.title)
        ? prev.filter(p => p.title !== product.title)
        : [...prev, product]
    );
  };

  // --- Email + Mailchimp ---
  const handleEmailSubmit = async () => {
    if (!email || !email.includes('@')) {
      setEmailError('Ingresa un email valido');
      return;
    }
    setEmailLoading(true);
    setEmailError('');
    try {
      await axios.post(`${API}/subscribe`, {
        email,
        skin_type: result?.tipo_piel || '',
        skin_tag:  result?.tipo_piel_tag || '',
        products:  selectedProducts
      });
      setEmailDone(true);
      setTimeout(() => { openCartUrl(); setShowModal(false); }, 1500);
    } catch (err) {
      console.error('Mailchimp error:', err);
      openCartUrl();
      setShowModal(false);
    } finally {
      setEmailLoading(false);
    }
  };

  // --- Carrito ---
  const openCartUrl = () => {
    const valid = selectedProducts.filter(p => p.variant_id);
    if (!valid.length) return;
    const url = `https://moonbow.cl/cart/${valid.map(p => `${p.variant_id}:1`).join(',')}`;
    console.log('Cart URL:', url);
    window.open(url, '_blank');
  };

  // --- WhatsApp ---
  const openWhatsApp = () => {
    const msg = `Hola Moonbow!\n\nResultado IA: ${result?.tipo_piel}\n${result?.analisis}\n\nProductos:\n${selectedProducts.map(p => `- ${p.title}`).join('\n')}`;
    window.open(`https://wa.me/+56912345678?text=${encodeURIComponent(msg)}`, '_blank');
  };

  const totalPrice = selectedProducts.reduce((acc, p) => acc + parseFloat(p.price || 0), 0);

  // --- Badges con valores reales de Gemini ---
  const badges = result ? [
    { icon: <Droplets size={15} color="#ff85a2" />, label: 'HIDRATACION',  value: result.hidratacion  || 'Optima' },
    { icon: <Activity size={15} color="#ff85a2" />, label: 'ELASTICIDAD',  value: result.elasticidad  ? `${result.elasticidad}%` : '85%' },
    { icon: <Zap      size={15} color="#ff85a2" />, label: 'SENSIBILIDAD', value: result.sensibilidad || 'Baja' },
    { icon: <span style={{ fontSize: '14px', lineHeight: '1' }}>age</span>, label: 'EDAD PIEL',   value: result.edad_piel    ? `${result.edad_piel} anos` : '--' }
  ] : [];

  return (
    <div style={{ fontFamily: "'Plus Jakarta Sans', sans-serif", maxWidth: '480px', margin: '0 auto', padding: '20px', backgroundColor: '#fffcfd', minHeight: '100vh', color: '#1a1a1a', paddingBottom: '140px' }}>

      {/* Header */}
      <header style={{ textAlign: 'center', marginBottom: '28px' }}>
        <div style={{ display: 'inline-block', padding: '6px 14px', background: '#fff', borderRadius: '100px', boxShadow: '0 4px 15px rgba(255,133,162,0.12)', marginBottom: '14px' }}>
          <span style={{ color: '#ff85a2', fontWeight: '800', fontSize: '11px', letterSpacing: '1.5px' }}>MOONBOW AI EXPERIENCE</span>
        </div>
        <h1 style={{ fontSize: '22px', fontWeight: '800', letterSpacing: '-0.5px', margin: 0 }}>Tu Diagnostico Personalizado</h1>
      </header>

      {/* Camara */}
      {!image && (
        <div style={{ textAlign: 'center' }}>
          <div style={{ borderRadius: '36px', overflow: 'hidden', backgroundColor: '#000', aspectRatio: '1/1', boxShadow: '0 20px 50px rgba(255,133,162,0.15)' }}>
            <video ref={videoRef} autoPlay playsInline style={{ width: '100%', height: '100%', objectFit: 'cover', transform: 'scaleX(-1)' }} />
          </div>
          {error && <p style={{ color: '#ff4444', marginTop: '12px', fontSize: '14px' }}>{error}</p>}
          <p style={{ color: '#bbb', fontSize: '13px', margin: '14px 0 8px' }}>Centra tu rostro con buena iluminacion</p>
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
            <button onClick={() => { setImage(null); setResult(null); setProducts([]); setSelectedProducts([]); setError(null); setEmailDone(false); }}
              style={{ width: '100%', background: '#f5f5f5', color: '#777', border: 'none', padding: '11px', borderRadius: '14px', fontWeight: '600', cursor: 'pointer', marginBottom: '16px', fontSize: '13px' }}>
              Tomar otra foto
            </button>
          )}

          {/* Cargando */}
          {loading && (
            <div style={{ textAlign: 'center', padding: '36px 0' }}>
              <div style={{ width: '44px', height: '44px', border: '3px solid #ffdae3', borderTop: '3px solid #ff85a2', borderRadius: '50%', margin: '0 auto 14px', animation: 'spin 0.8s linear infinite' }} />
              <p style={{ color: '#ff85a2', fontWeight: '700', fontSize: '15px', margin: 0 }}>Analizando tu piel con IA...</p>
              <p style={{ color: '#bbb', fontSize: '13px', margin: '6px 0 0' }}>Esto toma unos segundos</p>
            </div>
          )}

          {error && !loading && (
            <div style={{ textAlign: 'center', padding: '16px' }}>
              <p style={{ color: '#ff4444', marginBottom: '14px', fontSize: '14px' }}>{error}</p>
              <button onClick={() => runAnalysis(image)} style={{ background: '#ff85a2', color: 'white', border: 'none', padding: '12px 24px', borderRadius: '18px', fontWeight: '700', cursor: 'pointer' }}>
                Reintentar
              </button>
            </div>
          )}

          {result && !loading && (
            <div>

              {/* Badges — 4 columnas con edad piel */}
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '8px', marginBottom: '22px' }}>
                {badges.map((b, i) => (
                  <div key={i} style={{ background: 'white', padding: '12px 6px', borderRadius: '18px', textAlign: 'center', border: '1px solid #f0f0f0' }}>
                    <div style={{ marginBottom: '5px', display: 'flex', justifyContent: 'center', alignItems: 'center', height: '18px' }}>{b.icon}</div>
                    <p style={{ fontSize: '8px', fontWeight: '800', margin: '0 0 3px', color: '#ccc', letterSpacing: '0.4px' }}>{b.label}</p>
                    <p style={{ fontSize: '11px', fontWeight: '900', margin: 0, lineHeight: '1.2' }}>{b.value}</p>
                  </div>
                ))}
              </div>

              {/* Diagnostico */}
              <div style={{ padding: '24px', background: 'white', borderRadius: '28px', marginBottom: '20px', border: '1px solid #f8f8f8' }}>
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

              {/* Banner seleccion */}
              {selectedProducts.length > 0 && (
                <div style={{ padding: '16px 20px', background: '#fff5f7', borderRadius: '20px', border: '1.5px solid #ffdae3', marginBottom: '20px' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '6px' }}>
                    <Sparkles size={15} color="#ff85a2" />
                    <span style={{ fontSize: '13px', fontWeight: '800' }}>{selectedProducts.length} productos seleccionados</span>
                  </div>
                  <p style={{ margin: 0, fontSize: '12px', color: '#aaa', lineHeight: '1.5' }}>
                    Rutina personalizada para {result.tipo_piel.toLowerCase()}. Toca un producto para quitarlo.
                  </p>
                </div>
              )}

              {/* Lista de productos */}
              {products.length > 0 ? (
                <div style={{ marginBottom: '28px' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '14px' }}>
                    <h4 style={{ fontSize: '16px', fontWeight: '800', margin: 0 }}>Tu Rutina Personalizada</h4>
                    <span style={{ fontSize: '11px', color: '#ccc', fontWeight: '600' }}>Toca para editar</span>
                  </div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                    {STEPS.map((step, idx) => {
                      const prod = products.find(p => matchesStep(p.title, step.terms));
                      if (!prod) return null;
                      const isSel = !!selectedProducts.find(s => s.title === prod.title);
                      return (
                        <div key={idx} onClick={() => toggleProduct(prod)} style={{
                          display: 'flex', gap: '13px', padding: '13px',
                          background: isSel ? '#fffcfd' : '#fafafa',
                          borderRadius: '20px',
                          border: `2px solid ${isSel ? '#ff85a2' : '#efefef'}`,
                          cursor: 'pointer', transition: 'all 0.15s ease',
                          opacity: isSel ? 1 : 0.45
                        }}>
                          <div style={{ position: 'relative', flexShrink: 0 }}>
                            {prod.image
                              ? <img src={prod.image} alt={prod.title} style={{ width: '58px', height: '58px', borderRadius: '13px', objectFit: 'cover' }} />
                              : <div style={{ width: '58px', height: '58px', borderRadius: '13px', background: '#f0f0f0' }} />
                            }
                            {isSel && (
                              <div style={{ position: 'absolute', top: '-5px', right: '-5px', background: '#ff85a2', borderRadius: '50%', width: '19px', height: '19px', display: 'flex', alignItems: 'center', justifyContent: 'center', border: '2px solid white' }}>
                                <Check size={10} color="white" strokeWidth={4} />
                              </div>
                            )}
                          </div>
                          <div style={{ flex: 1, minWidth: 0 }}>
                            <p style={{ fontSize: '9px', fontWeight: '800', color: '#ff85a2', margin: '0 0 3px', textTransform: 'uppercase', letterSpacing: '0.3px' }}>{step.label}</p>
                            <p style={{ fontSize: '12px', fontWeight: '700', margin: '0 0 4px', lineHeight: '1.2', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{prod.title}</p>
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

              {/* WhatsApp */}
              <button onClick={openWhatsApp} style={{ width: '100%', background: '#fff', color: '#25D366', border: '2px solid #25D366', padding: '15px', borderRadius: '18px', fontWeight: '800', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '10px', fontSize: '14px' }}>
                <MessageCircle size={17} /> Hablar con una experta
              </button>

            </div>
          )}
        </div>
      )}

      {/* Boton flotante carrito */}
      {selectedProducts.length > 0 && result && !loading && (
        <div style={{ position: 'fixed', bottom: '20px', left: '20px', right: '20px', zIndex: 100 }}>
          <button onClick={() => setShowModal(true)}
            style={{ width: '100%', background: '#1a1a1a', color: 'white', border: 'none', padding: '19px 22px', borderRadius: '26px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', boxShadow: '0 15px 40px rgba(0,0,0,0.2)', cursor: 'pointer' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '11px' }}>
              <ShoppingBag size={19} color="#ff85a2" />
              <span style={{ fontWeight: '800', fontSize: '14px' }}>Agregar {selectedProducts.length} al carro</span>
            </div>
            <span style={{ fontWeight: '900', fontSize: '16px' }}>${Math.round(totalPrice).toLocaleString('es-CL')}</span>
          </button>
        </div>
      )}

      {/* Modal email + checkout */}
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
                <p style={{ color: '#bbb', fontSize: '13px', margin: 0 }}>Te enviamos tu rutina por email.</p>
              </div>
            ) : (
              <>
                {/* Resumen */}
                <div style={{ display: 'flex', alignItems: 'center', gap: '13px', marginBottom: '20px' }}>
                  <div style={{ width: '48px', height: '48px', background: '#fff5f7', borderRadius: '18px', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
                    <ShoppingBag size={22} color="#ff85a2" />
                  </div>
                  <div>
                    <p style={{ margin: 0, fontWeight: '800', fontSize: '15px' }}>{selectedProducts.length} productos</p>
                    <p style={{ margin: '2px 0 0', color: '#999', fontSize: '13px' }}>Rutina para {result?.tipo_piel}</p>
                  </div>
                  <div style={{ marginLeft: 'auto' }}>
                    <p style={{ margin: 0, fontWeight: '900', fontSize: '17px' }}>${Math.round(totalPrice).toLocaleString('es-CL')}</p>
                  </div>
                </div>

                {/* Detalle productos */}
                <div style={{ borderTop: '1px solid #f5f5f5', borderBottom: '1px solid #f5f5f5', padding: '12px 0', marginBottom: '18px' }}>
                  {selectedProducts.map((p, i) => (
                    <div key={i} style={{ display: 'flex', justifyContent: 'space-between', padding: '6px 0', fontSize: '12px' }}>
                      <span style={{ color: '#555', flex: 1, marginRight: '8px', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{p.title}</span>
                      <span style={{ fontWeight: '700', flexShrink: 0 }}>${Math.round(parseFloat(p.price)).toLocaleString('es-CL')}</span>
                    </div>
                  ))}
                </div>

                {/* Captura email */}
                <div style={{ background: '#fff5f7', borderRadius: '20px', padding: '18px', marginBottom: '14px' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '7px', marginBottom: '6px' }}>
                    <Mail size={14} color="#ff85a2" />
                    <span style={{ fontSize: '13px', fontWeight: '800' }}>Recibe tu rutina por email</span>
                  </div>
                  <p style={{ fontSize: '11px', color: '#bbb', margin: '0 0 12px' }}>Te guardamos los productos para que no los pierdas.</p>
                  <input
                    type="email"
                    value={email}
                    onChange={e => { setEmail(e.target.value); setEmailError(''); }}
                    placeholder="tu@email.com"
                    style={{ width: '100%', padding: '11px 14px', borderRadius: '12px', border: emailError ? '1.5px solid #ff4444' : '1.5px solid #ffdae3', fontSize: '14px', outline: 'none', background: 'white', boxSizing: 'border-box' }}
                  />
                  {emailError && <p style={{ color: '#ff4444', fontSize: '11px', margin: '5px 0 0' }}>{emailError}</p>}
                </div>

                <button onClick={handleEmailSubmit} disabled={emailLoading}
                  style={{ width: '100%', background: '#ff85a2', color: 'white', border: 'none', padding: '17px', borderRadius: '20px', fontWeight: '800', fontSize: '15px', cursor: emailLoading ? 'not-allowed' : 'pointer', opacity: emailLoading ? 0.8 : 1, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '9px', marginBottom: '10px' }}>
                  {emailLoading ? 'Procesando...' : <><span>Ir al Carrito de Moonbow</span><ArrowRight size={17} /></>}
                </button>

                <button onClick={() => { openCartUrl(); setShowModal(false); }}
                  style={{ width: '100%', background: 'transparent', color: '#ccc', border: 'none', padding: '10px', cursor: 'pointer', fontSize: '12px', fontWeight: '600' }}>
                  Ir al carrito sin guardar mi rutina
                </button>
              </>
            )}
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