import { useEffect, useMemo, useRef, useState } from 'react'
import { createRoot } from 'react-dom/client'
import './styles.css'

const API = import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000'
const currency = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 })
const prompts = ['Show me office chairs under $500', 'Find a desk for a small home office', 'Show my cart', 'Find a chair and add the second one to my cart']

function Icon({ name, size = 20 }) {
  const paths = {
    bag: <><path d="M5 8h14l-1 13H6L5 8Z"/><path d="M9 9V6a3 3 0 0 1 6 0v3"/></>,
    spark: <path d="m12 2 1.9 6.1L20 10l-6.1 1.9L12 18l-1.9-6.1L4 10l6.1-1.9L12 2Z"/>,
    arrow: <><path d="M5 12h14"/><path d="m13 6 6 6-6 6"/></>,
    plus: <><path d="M12 5v14M5 12h14"/></>,
    minus: <path d="M5 12h14"/>,
    close: <><path d="m6 6 12 12M18 6 6 18"/></>,
    send: <path d="m21 3-7.5 18-3.6-7.9L3 9.5 21 3Z"/>,
    leaf: <path d="M20 4C11 4 4 8 4 16c0 2.1 1.7 4 4.3 4 6.7 0 10.5-8.2 11.7-16ZM4 20c3-4 7-7 12-9"/>,
    check: <path d="m5 12 4.2 4L19 6"/>
  }
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name]}</svg>
}

function ProductCard({ product, onAdd, compact = false }) {
  return <article className={`product-card ${compact ? 'compact' : ''}`}>
    <div className={`product-art art-${product.id % 5}`}><span>{product.category.split(' ')[0]}</span><b>{product.sku}</b></div>
    <div className="product-copy">
      <p className="eyebrow">{product.category}</p>
      <h3>{product.title}</h3>
      {!compact && <p className="product-description">{product.description}</p>}
      <div className="rating"><span>★</span> {product.rating} <i>·</i> {product.color}</div>
      <div className="product-bottom"><strong>{currency.format(product.price)}</strong><button className="add-button" onClick={() => onAdd(product)} aria-label={`Add ${product.title}`}><Icon name="plus" size={16}/>{!compact && ' Add'}</button></div>
    </div>
  </article>
}

function App() {
  const [sessionId] = useState(() => {
    const old = localStorage.getItem('shop-buddy-session')
    if (old) return old
    const fresh = crypto.randomUUID()
    localStorage.setItem('shop-buddy-session', fresh)
    return fresh
  })
  const [messages, setMessages] = useState([{ role: 'assistant', content: 'Hi, I’m Shop Buddy. Tell me how your space needs to feel, and I’ll help find the right pieces.', products: [] }])
  const [input, setInput] = useState('')
  const [cart, setCart] = useState({ items: [], total: 0, item_count: 0 })
  const [catalog, setCatalog] = useState([])
  const [isSending, setIsSending] = useState(false)
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [notice, setNotice] = useState('')
  const [service, setService] = useState({ status: 'checking' })
  const [token, setToken] = useState(() => localStorage.getItem('shop-buddy-token') || '')
  const [user, setUser] = useState(null)
  const [preferences, setPreferences] = useState({ favorite_categories: [], favorite_colors: [], room: '', budget: null })
  const [recommendations, setRecommendations] = useState([])
  const [authOpen, setAuthOpen] = useState(false)
  const [authMode, setAuthMode] = useState('login')
  const [authBusy, setAuthBusy] = useState(false)
  const [authError, setAuthError] = useState('')
  const [authForm, setAuthForm] = useState({ name: '', email: '', password: '' })
  const [preferenceForm, setPreferenceForm] = useState({ categories: '', colors: '', room: '', budget: '' })
  const messagesRef = useRef(null)

  const request = async (path, options = {}) => {
    const headers = { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}), ...(options.headers || {}) }
    const response = await fetch(`${API}${path}`, { ...options, headers })
    const data = await response.json().catch(() => ({}))
    if (!response.ok) throw new Error(data.detail || 'Something went wrong. Please try again.')
    return data
  }
  const refreshCart = async () => {
    const data = await request(`/get_cart_items/?session_id=${encodeURIComponent(sessionId)}`)
    setCart(data)
  }
  useEffect(() => {
    refreshCart().catch(() => setService({ status: 'offline' }))
    request('/api/products').then(data => setCatalog(data.products)).catch(() => {})
    request('/health').then(setService).catch(() => setService({ status: 'offline' }))
    if (token) {
      request('/auth/me').then(data => {
        setUser(data.user); setPreferences(data.preferences)
        setPreferenceForm({ categories: data.preferences.favorite_categories.join(', '), colors: data.preferences.favorite_colors.join(', '), room: data.preferences.room || '', budget: data.preferences.budget || '' })
        return request('/recommendations')
      }).then(data => setRecommendations(data.products)).catch(() => {
        localStorage.removeItem('shop-buddy-token'); setToken(''); setUser(null); setRecommendations([])
      })
    } else { setUser(null); setRecommendations([]) }
  }, [token])
  useEffect(() => {
    // Keep new messages visible inside the fixed-height chat pane only. Calling
    // scrollIntoView on an anchor also scrolls the document to the catalog area.
    const panel = messagesRef.current
    if (panel) panel.scrollTop = panel.scrollHeight
  }, [messages, isSending])

  const send = async (text = input) => {
    const clean = text.trim()
    if (!clean || isSending) return
    setMessages(current => [...current, { role: 'user', content: clean }])
    setInput(''); setIsSending(true); setNotice('')
    try {
      const data = await request('/chat', { method: 'POST', body: JSON.stringify({ message: clean, session_id: sessionId }) })
      setMessages(current => [...current, { role: 'assistant', content: data.message, products: data.products || [], trace: data.trace, provider: data.provider }])
      setCart(data.cart)
      if (data.recommendations) setRecommendations(data.recommendations)
    } catch (error) {
      setMessages(current => [...current, { role: 'assistant', error: true, content: error.message }])
    } finally { setIsSending(false) }
  }
  const addProduct = async (product) => {
    try {
      const data = await request('/add_product_to_cart/', { method: 'POST', body: JSON.stringify({ product_id: product.id, quantity: 1, session_id: sessionId }) })
      setCart(data.cart); setNotice(`${product.title} added to your cart.`); setDrawerOpen(true)
    } catch (error) { setNotice(error.message) }
  }
  const changeQuantity = async (item, quantity) => {
    if (quantity < 1) return removeItem(item)
    try {
      const data = await request('/update_product_in_cart/', { method: 'PUT', body: JSON.stringify({ cart_item_id: item.cart_item_id, quantity, session_id: sessionId }) })
      setCart(data.cart)
    } catch (error) { setNotice(error.message) }
  }
  const removeItem = async (item) => {
    try {
      const data = await request('/delete_product_from_cart/', { method: 'DELETE', body: JSON.stringify({ cart_item_id: item.cart_item_id, session_id: sessionId }) })
      setCart(data.cart)
    } catch (error) { setNotice(error.message) }
  }
  const submitAuth = async (event) => {
    event.preventDefault(); setAuthError(''); setAuthBusy(true)
    try {
      const path = authMode === 'register' ? '/auth/register' : '/auth/login'
      const body = authMode === 'register' ? authForm : { email: authForm.email, password: authForm.password }
      const data = await request(path, { method: 'POST', body: JSON.stringify(body) })
      localStorage.setItem('shop-buddy-token', data.token); setToken(data.token); setUser(data.user); setPreferences(data.preferences)
      setPreferenceForm({ categories: data.preferences.favorite_categories.join(', '), colors: data.preferences.favorite_colors.join(', '), room: data.preferences.room || '', budget: data.preferences.budget || '' })
      setAuthOpen(false); setAuthForm({ name: '', email: '', password: '' }); setNotice(`Welcome, ${data.user.name}. Your cart and preferences are now saved.`)
    } catch (error) { setAuthError(error.message) } finally { setAuthBusy(false) }
  }
  const savePreferences = async (event) => {
    event.preventDefault(); setAuthError(''); setAuthBusy(true)
    const split = value => value.split(',').map(item => item.trim()).filter(Boolean)
    try {
      const data = await request('/preferences', { method: 'PUT', body: JSON.stringify({ favorite_categories: split(preferenceForm.categories), favorite_colors: split(preferenceForm.colors), room: preferenceForm.room, budget: preferenceForm.budget ? Number(preferenceForm.budget) : null }) })
      setPreferences(data)
      const suggestions = await request('/recommendations'); setRecommendations(suggestions.products)
      setNotice('Your preferences are saved. New recommendations are ready.'); setAuthOpen(false)
    } catch (error) { setAuthError(error.message) } finally { setAuthBusy(false) }
  }
  const signOut = async () => {
    try { await request('/auth/logout', { method: 'POST' }) } catch { /* Token may already be expired. */ }
    localStorage.removeItem('shop-buddy-token'); setToken(''); setUser(null); setRecommendations([]); setAuthOpen(false); setNotice('You are signed out. Anonymous shopping is still available.')
  }
  const categories = useMemo(() => [...new Set(catalog.map(item => item.category))], [catalog])

  return <div className="app-shell">
    <header className="topbar">
      <a className="brand" href="#top"><span className="brand-mark"><Icon name="leaf" size={22}/></span><span>UrbanNest<small>FURNISHINGS</small></span></a>
      <div className="top-actions"><span className={`status ${service.status === 'ok' ? 'online' : ''}`}><i></i>{service.status === 'ok' ? 'Shop Buddy is ready' : 'Connecting'}</span><button className="account-trigger" onClick={() => { setAuthError(''); setAuthOpen(true) }}>{user ? user.name.split(' ')[0] : 'Sign in'}</button><button className="cart-trigger" onClick={() => setDrawerOpen(true)}><Icon name="bag" size={19}/><span>Cart</span>{cart.item_count > 0 && <b>{cart.item_count}</b>}</button></div>
    </header>
    <main id="top">
      <section className="hero">
        <div className="hero-copy"><p className="section-label"><Icon name="spark" size={14}/> YOUR PERSONAL SHOPPING GUIDE</p><h1>Make space for<br/><em>better living.</em></h1><p>Describe the room you’re creating. Shop Buddy searches UrbanNest’s collection, remembers your choices, and takes care of your cart.</p><div className="hero-badges"><span><Icon name="check" size={14}/> Thoughtful matches</span><span><Icon name="check" size={14}/> Cart-ready picks</span></div></div>
        <div className="hero-art"><div className="sun"></div><div className="arch"></div><div className="chair-shape"><i></i><b></b><span></span></div><p>CURATED FOR<br/>YOUR CORNER</p></div>
      </section>
      <section className="experience">
        <aside className="discover-panel"><p className="section-label">EXPLORE THE COLLECTION</p><h2>Start with<br/>a feeling.</h2><div className="category-list">{categories.slice(0, 6).map(category => <button key={category} onClick={() => send(`Show me ${category}`)}>{category}<Icon name="arrow" size={15}/></button>)}</div></aside>
        <section className="chat-panel" aria-label="Shop Buddy conversation">
          <div className="chat-heading"><div><p className="section-label">AI SHOPPING ASSISTANT</p><h2>Ask Shop Buddy</h2></div><span className="secure"><Icon name="spark" size={15}/> remembers your picks</span></div>
          <div className="messages" ref={messagesRef}>{messages.map((message, index) => <div className={`message-row ${message.role} ${message.error ? 'error' : ''}`} key={index}><div className="avatar">{message.role === 'assistant' ? <Icon name="spark" size={16}/> : 'You'}</div><div className="bubble"><p>{message.content}</p>{message.products?.length > 0 && <div className="result-grid">{message.products.slice(0, 4).map(product => <ProductCard key={product.id} product={product} onAdd={addProduct} compact/>)}</div>} {message.trace && <details><summary>View shopping workflow</summary><ul>{message.trace.map(step => <li key={step.agent}>{step.agent}: {step.detail}</li>)}</ul></details>}</div></div>)}{isSending && <div className="message-row assistant"><div className="avatar"><Icon name="spark" size={16}/></div><div className="bubble typing"><span></span><span></span><span></span></div></div>}</div>
          <div className="prompt-row">{prompts.map(prompt => <button key={prompt} onClick={() => send(prompt)}>{prompt}</button>)}</div>
          <form className="composer" onSubmit={event => { event.preventDefault(); send() }}><input value={input} onChange={event => setInput(event.target.value)} placeholder="Try “find a warm reading chair under $500”" aria-label="Message Shop Buddy"/><button type="submit" disabled={!input.trim() || isSending}><Icon name="send" size={18}/></button></form>
        </section>
      </section>
      {catalog.length > 0 && <section className="catalog-section"><div><p className="section-label">URBANNEST FAVORITES</p><h2>Pieces with presence.</h2></div><div className="catalog-grid">{catalog.slice(0, 4).map(product => <ProductCard key={product.id} product={product} onAdd={addProduct}/>)}</div></section>}
      {user && recommendations.length > 0 && <section className="catalog-section recommendations"><div><p className="section-label"><Icon name="spark" size={14}/> PERSONALIZED FOR {user.name.toUpperCase()}</p><h2>More your kind of space.</h2><p className="recommendation-copy">Suggestions learn from your saved room details, favorites, and the pieces you explore or add.</p></div><div className="catalog-grid">{recommendations.map(product => <ProductCard key={product.id} product={product} onAdd={addProduct}/>)}</div></section>}
    </main>
    {notice && <div className="toast"><Icon name="check" size={17}/>{notice}<button onClick={() => setNotice('')}><Icon name="close" size={15}/></button></div>}
    {authOpen && <div className="modal-backdrop" onClick={() => setAuthOpen(false)}><section className="account-modal" onClick={event => event.stopPropagation()} aria-label="Account and preferences"><button className="modal-close" onClick={() => setAuthOpen(false)} aria-label="Close account"><Icon name="close" size={18}/></button>{user ? <><p className="section-label"><Icon name="spark" size={14}/> YOUR URBANNEST PROFILE</p><h2>Make recommendations personal.</h2><p className="modal-intro">Signed in as <strong>{user.email}</strong>. We keep your cart, chat context, and these preferences in your account.</p><form className="account-form" onSubmit={savePreferences}><label>Favorite categories<input value={preferenceForm.categories} onChange={event => setPreferenceForm(current => ({ ...current, categories: event.target.value }))} placeholder="Office Chairs, Desks"/></label><label>Colors you love<input value={preferenceForm.colors} onChange={event => setPreferenceForm(current => ({ ...current, colors: event.target.value }))} placeholder="Graphite, Natural"/></label><label>Room or project<input value={preferenceForm.room} onChange={event => setPreferenceForm(current => ({ ...current, room: event.target.value }))} placeholder="Home office"/></label><label>Maximum piece budget<input type="number" min="1" value={preferenceForm.budget} onChange={event => setPreferenceForm(current => ({ ...current, budget: event.target.value }))} placeholder="500"/></label>{authError && <p className="form-error">{authError}</p>}<button className="account-submit" disabled={authBusy}>{authBusy ? 'Saving…' : 'Save preferences'}</button></form><button className="signout" onClick={signOut}>Sign out</button></> : <><p className="section-label"><Icon name="spark" size={14}/> SAVE YOUR SPACE</p><h2>{authMode === 'register' ? 'Create your account.' : 'Welcome back.'}</h2><p className="modal-intro">Save your cart, preserve chat memory, and get recommendations that improve with every visit.</p><form className="account-form" onSubmit={submitAuth}>{authMode === 'register' && <label>Your name<input required value={authForm.name} onChange={event => setAuthForm(current => ({ ...current, name: event.target.value }))} placeholder="Alex Morgan"/></label>}<label>Email address<input required type="email" value={authForm.email} onChange={event => setAuthForm(current => ({ ...current, email: event.target.value }))} placeholder="you@example.com"/></label><label>Password<input required type="password" minLength="8" value={authForm.password} onChange={event => setAuthForm(current => ({ ...current, password: event.target.value }))} placeholder="At least 8 characters"/></label>{authError && <p className="form-error">{authError}</p>}<button className="account-submit" disabled={authBusy}>{authBusy ? 'Please wait…' : authMode === 'register' ? 'Create account' : 'Sign in'}</button></form><button className="auth-switch" onClick={() => { setAuthMode(mode => mode === 'login' ? 'register' : 'login'); setAuthError('') }}>{authMode === 'login' ? 'New to UrbanNest? Create an account' : 'Already have an account? Sign in'}</button></>}</section></div>}
    <div className={`drawer-backdrop ${drawerOpen ? 'show' : ''}`} onClick={() => setDrawerOpen(false)}></div>
    <aside className={`cart-drawer ${drawerOpen ? 'open' : ''}`} aria-label="Shopping cart"><div className="drawer-head"><div><p className="section-label">YOUR SELECTIONS</p><h2>Cart ({cart.item_count})</h2></div><button onClick={() => setDrawerOpen(false)} aria-label="Close cart"><Icon name="close"/></button></div>{cart.items.length === 0 ? <div className="empty-cart"><span><Icon name="bag" size={30}/></span><h3>Your cart is open to possibility.</h3><p>Add a piece you love and it will appear here.</p></div> : <><div className="cart-lines">{cart.items.map(item => <div className="cart-line" key={item.cart_item_id}><div className={`mini-art art-${item.product_id % 5}`}></div><div><h3>{item.title}</h3><p>{currency.format(item.unit_price)} · {item.color}</p><div className="line-actions"><div className="quantity"><button onClick={() => changeQuantity(item, item.quantity - 1)}><Icon name="minus" size={13}/></button><span>{item.quantity}</span><button onClick={() => changeQuantity(item, item.quantity + 1)}><Icon name="plus" size={13}/></button></div><button className="remove" onClick={() => removeItem(item)}>Remove</button></div></div><strong>{currency.format(item.subtotal)}</strong></div>)}</div><div className="cart-total"><span>Subtotal</span><strong>{currency.format(cart.total)}</strong><small>Taxes and delivery calculated at checkout.</small><button className="checkout" onClick={() => setNotice('Your cart is ready. Checkout can be connected to your preferred payment provider.')}>Proceed to checkout <Icon name="arrow" size={17}/></button></div></>}</aside>
  </div>
}

createRoot(document.getElementById('root')).render(<App />)
