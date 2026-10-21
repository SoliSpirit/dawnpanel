import React from 'react';
import { createRoot } from 'react-dom/client';
import { gsap } from 'gsap';
import { ScrollTrigger } from 'gsap/ScrollTrigger';
import Lenis from 'lenis';
import 'lenis/dist/lenis.css';
import SpotlightCard from './react-bits/SpotlightCard.jsx';
import './storefront.css';

gsap.registerPlugin(ScrollTrigger);
const motionPreference = matchMedia('(prefers-reduced-motion: reduce)');
const pointerPreference = matchMedia('(hover: hover) and (pointer: fine)');
const roots = [];
function renderSpotlight(root, color) {
  const light = document.documentElement.dataset.theme === 'light';
  root.render(<SpotlightCard theme={light ? 'light' : 'dark'} className="store-spotlight" spotlightColor={color} intensity={light ? 0.4 : 0.17} borderGlow={0.45} spotlightSize={300} flare={false} proximity={40} />);
}
document.addEventListener('dawn:theme-change', () => roots.forEach(({root, color}) => renderSpotlight(root, color)));
let lenis;
let ticker;
let context;
let active = false;

function start() {
  if (active || motionPreference.matches) return;
  active = true;
  if (pointerPreference.matches) {
    // Decorative React islands leave the original links, text and prices in Django's HTML.
    document.querySelectorAll('[data-store-card]').forEach(card => {
      const host = document.createElement('div');
      host.className = 'spotlight-host';
      host.setAttribute('aria-hidden', 'true');
      card.prepend(host);
      const color = card.querySelector('.ai') ? '#bbabff' : card.querySelector('.rubika') ? '#79c8ff' : card.querySelector('.eitaa') ? '#ffbb83' : '#81eadb';
      const root = createRoot(host);
      renderSpotlight(root, color);
      roots.push({ root, host, color });
    });
    lenis = new Lenis({ duration: 1.05, smoothWheel: true, syncTouch: false, anchors: true, prevent: node => Boolean(node.closest('textarea,select,[data-lenis-prevent],.table-wrap')) });
    lenis.on('scroll', ScrollTrigger.update);
    ticker = time => lenis.raf(time * 1000);
    gsap.ticker.add(ticker);
  }
  context = gsap.context(() => {
    const entrance = document.querySelectorAll('.hero-copy > *, .page-head > *');
    if (entrance.length) gsap.from(entrance, { y: 20, opacity: 0, duration: 0.75, stagger: 0.09, ease: 'power2.out', clearProps: 'all' });
    if (document.querySelector('.hero-art')) gsap.from('.hero-art', { scale: 0.94, opacity: 0, duration: 1, ease: 'power2.out', clearProps: 'all' });
    document.querySelectorAll('.cards, .feature-panel, .cta, .detail-grid').forEach(section => {
      const targets = section.matches('.cards') ? section.children : [section];
      gsap.from(targets, { y: 25, opacity: 0, duration: 0.65, stagger: 0.07, ease: 'power2.out', clearProps: 'all', scrollTrigger: { trigger: section, start: 'top 94%', once: true } });
    });
    // Finite motion keeps the storefront calm after its opening sequence.
    if (document.querySelector('.network')) gsap.fromTo('.network', { y: 9 }, { y: -5, duration: 2, stagger: 0.2, yoyo: true, repeat: 3, ease: 'sine.inOut' });
    if (document.querySelector('.art-order')) gsap.from('.art-order', { y: 20, opacity: 0, delay: 0.55, duration: 0.8, clearProps: 'all' });
  });
  document.documentElement.dataset.storeMotion = 'enabled';
}
function stop() {
  context?.revert();
  context = undefined;
  if (ticker) gsap.ticker.remove(ticker);
  ticker = undefined;
  lenis?.destroy();
  lenis = undefined;
  roots.splice(0).forEach(({ root, host }) => { root.unmount(); host.remove(); });
  delete document.documentElement.dataset.storeMotion;
  active = false;
}
const update = () => { stop(); start(); };
motionPreference.addEventListener('change', update);
pointerPreference.addEventListener('change', update);
window.addEventListener('pagehide', stop);
window.addEventListener('pageshow', event => { if (event.persisted) start(); });
start();
