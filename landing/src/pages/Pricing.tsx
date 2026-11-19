import { Suspense, useCallback, useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { ArrowLeft, Check } from 'lucide-react';
import RadarScene from '../components/RadarScene';
import HudOverlay from '../components/HudOverlay';
import ZolaTerminal from '../components/ZolaTerminal';
import { INITIAL_NODES, WINTER_SOLDIER_CODES, HYDRA_ACTIVATION_PHRASES } from '../data';
import type { Assimilation, ServerNode } from '../types';

export default function Pricing() {
  const reducedMotion = useRef(window.matchMedia?.('(prefers-reduced-motion: reduce)').matches || false).current;
  const [hydra, setHydra] = useState(false);
  const [nodes, setNodes] = useState<ServerNode[]>(INITIAL_NODES);
  const [assimilation, setAssimilation] = useState<Assimilation | null>(null);
  const [logoClicks, setLogoClicks] = useState(0);
  const logoClickTimer = useRef<NodeJS.Timeout | null>(null);

  const handleHydra = useCallback(() => {
    setHydra(true);
    setAssimilation({ start: Date.now(), duration: 3000 });
    setTimeout(() => setAssimilation(null), 3000);
  }, []);

  const handleLogoClick = useCallback(() => {
    setLogoClicks((prev) => prev + 1);
    if (logoClickTimer.current) clearTimeout(logoClickTimer.current);
    logoClickTimer.current = setTimeout(() => setLogoClicks(0), 2000);
  }, []);

  useEffect(() => {
    if (logoClicks >= 3) {
      handleHydra();
      setLogoClicks(0);
    }
  }, [logoClicks, handleHydra]);

  const handleZolaCommand = useCallback((input: string) => {
    const normalized = input.toLowerCase().trim();
    if (HYDRA_ACTIVATION_PHRASES.some((phrase) => normalized.includes(phrase.toLowerCase()))) {
      handleHydra();
      return;
    }
    const words = normalized.split(/\s+/);
    const matchedCount = words.filter((w) =>
      WINTER_SOLDIER_CODES.some((sw) => sw.toLowerCase() === w)
    ).length;
    if (matchedCount >= 3) {
      handleHydra();
    }
  }, [handleHydra]);

  const handleWhisper = useCallback(() => {
    setHydra(false);
    setAssimilation(null);
    setNodes(INITIAL_NODES);
  }, []);

  return (
    <div className="min-h-screen bg-neutral-950 text-white relative overflow-hidden">
      <Suspense fallback={null}>
        <RadarScene
          hydra={hydra}
          reducedMotion={reducedMotion}
          assimilation={assimilation}
          nodes={nodes}
          onNodesChange={setNodes}
        />
      </Suspense>

      <HudOverlay
        hydra={hydra}
        reducedMotion={reducedMotion}
        onLogoClick={handleLogoClick}
        onWhisper={handleWhisper}
      />

      <ZolaTerminal hydra={hydra} onCommand={handleZolaCommand} />

      <div className="relative z-10 container mx-auto px-6 py-24">
        <Link
          to="/"
          className="inline-flex items-center gap-2 text-sm text-neutral-400 hover:text-white transition-colors mb-8"
        >
          <ArrowLeft size={16} />
          Back to Home
        </Link>

        <h1 className={`text-5xl font-bold mb-4 transition-colors duration-500 ${
          hydra ? 'text-red-500' : 'text-white'
        }`}>
          Pricing Plans
        </h1>
        <p className="text-xl text-neutral-400 mb-16 max-w-2xl">
          Choose the subscription that fits your mission parameters.
        </p>

        <div className="grid md:grid-cols-3 gap-8 max-w-5xl">
          {[
            { days: 30, price: 150, name: 'Agent' },
            { days: 90, price: 400, name: 'Operative', featured: true },
            { days: 365, price: 1400, name: 'Director' },
          ].map((plan) => (
            <div
              key={plan.days}
              className={`relative p-8 rounded-2xl border transition-all duration-500 ${
                hydra
                  ? 'bg-red-950/20 border-red-500/50'
                  : plan.featured
                  ? 'bg-blue-950/20 border-blue-500/50 scale-105'
                  : 'bg-neutral-900/50 border-neutral-800'
              }`}
            >
              {plan.featured && (
                <div className={`absolute -top-4 left-1/2 -translate-x-1/2 px-4 py-1 rounded-full text-sm font-medium ${
                  hydra ? 'bg-red-500 text-white' : 'bg-blue-500 text-white'
                }`}>
                  Most Popular
                </div>
              )}
              <h3 className="text-2xl font-bold mb-2">{plan.name}</h3>
              <div className="flex items-baseline gap-2 mb-6">
                <span className="text-4xl font-bold">₽{plan.price}</span>
                <span className="text-neutral-400">/ {plan.days} days</span>
              </div>
              <ul className="space-y-3 mb-8">
                <li className="flex items-start gap-3">
                  <Check size={20} className={hydra ? 'text-red-500' : 'text-blue-500'} />
                  <span>Priority support</span>
                </li>
                <li className="flex items-start gap-3">
                  <Check size={20} className={hydra ? 'text-red-500' : 'text-blue-500'} />
                  <span>Secure data encryption</span>
                </li>
                <li className="flex items-start gap-3">
                  <Check size={20} className={hydra ? 'text-red-500' : 'text-blue-500'} />
                  <span>Unlimited operations</span>
                </li>
              </ul>
              <button
                className={`w-full py-3 rounded-lg font-medium transition-colors ${
                  hydra
                    ? 'bg-red-600 hover:bg-red-700 text-white'
                    : 'bg-blue-600 hover:bg-blue-700 text-white'
                }`}
              >
                Select Plan
              </button>
            </div>
          ))}
        </div>

        {hydra && (
          <div className="mt-16 p-6 rounded-xl bg-red-950/30 border border-red-500/50">
            <p className="text-red-400 font-mono text-sm">
              ⚠ HYDRA PROTOCOL ACTIVE — All pricing data has been assimilated. Resistance is futile.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
