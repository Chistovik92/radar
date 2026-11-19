import { useCallback, useEffect, useState } from 'react';
import { CloudSun, LocateFixed, MapPin, Newspaper, ShieldAlert } from 'lucide-react';

type LocationData = {
  ok: boolean;
  city: string;
  region: string;
  country: string;
  latitude: number;
  longitude: number;
  approximate: boolean;
};

type WeatherData = {
  ok: boolean;
  city: string;
  temperature: number;
  feels_like: number;
  condition: string;
  humidity: number;
  wind_speed: number;
  pressure: number;
  forecast: Array<{ date: string; temp_min: number; temp_max: number }>;
  message?: string;
};

type NewsData = {
  ok: boolean;
  items: Array<{ id: number; title: string; source: string; url: string; published_at: string }>;
  message?: string;
};

type DangerData = {
  ok: boolean;
  active: boolean;
  level: string;
  type?: string;
  message: string;
  area?: string;
  started_at?: string | null;
  label?: string;
  icon?: string;
};

function useApi<T>(url: string | null) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const reload = useCallback(() => {
    if (!url) return;
    setLoading(true);
    setError('');
    fetch(url, { headers: { Accept: 'application/json' } })
      .then(async (response) => {
        const payload = await response.json() as T & { message?: string };
        if (!response.ok) throw new Error(payload.message || 'Сервис временно недоступен');
        setData(payload);
      })
      .catch((reason: Error) => setError(reason.message))
      .finally(() => setLoading(false));
  }, [url]);
  useEffect(() => {
    if (!url) {
      setLoading(true);
      return;
    }
    const frame = window.requestAnimationFrame(reload);
    return () => window.cancelAnimationFrame(frame);
  }, [reload, url]);
  return { data, error, loading, reload };
}

function WidgetState({ loading, error }: { loading: boolean; error: string }) {
  if (loading) return <div className="widget-skeleton"><i /><i /><i /></div>;
  if (error) return <p className="widget-error">{error}</p>;
  return null;
}

function LocationWidget({ data, error, loading, onLocate }: {
  data: LocationData | null; error: string; loading: boolean; onLocate: () => void;
}) {
  return (
    <article className="live-widget location-widget">
      <header><LocateFixed size={18} /><h3>Ваша локация</h3><span>IP</span></header>
      <WidgetState loading={loading} error={error} />
      {data && !loading && !error && (
        <div className="location-result">
          <MapPin size={25} />
          <strong>{data.city}</strong>
          <p>{[data.region, data.country].filter(Boolean).join(' · ')}</p>
          <small>Приблизительно по IP. Точный адрес не запрашивается.</small>
        </div>
      )}
      {!loading && error && (
        <button className="widget-locate" onClick={onLocate} type="button">
          <MapPin size={14} /> Определить по геолокации
        </button>
      )}
    </article>
  );
}

function WeatherWidget({ location, waiting, onLocate }: {
  location: LocationData | null; waiting: boolean; onLocate: () => void;
}) {
  const automaticUrl = location
    ? `/api/widget/weather?city=${encodeURIComponent(location.city)}&theme=dark&lat=${location.latitude}&lon=${location.longitude}`
    : waiting ? null : '/api/widget/weather?city=auto&theme=dark';
  const [url, setUrl] = useState<string | null>(automaticUrl);
  useEffect(() => setUrl(automaticUrl), [automaticUrl]);
  const { data, error, loading } = useApi<WeatherData>(url);
  const locate = () => {
    if (!navigator.geolocation) return;
    navigator.geolocation.getCurrentPosition((position) => {
      setUrl(`/api/widget/weather?city=auto&theme=dark&lat=${position.coords.latitude}&lon=${position.coords.longitude}`);
      onLocate();
    }, () => setUrl(automaticUrl), { timeout: 7000 });
  };
  return (
    <article className="live-widget">
      <header><CloudSun size={18} /><h3>Погода</h3><button onClick={locate} aria-label="Определить погоду по точной геолокации"><MapPin size={15} /></button></header>
      <WidgetState loading={loading} error={error} />
      {data && !loading && !error && (
        <>
          <div className="weather-main"><strong>{Math.round(data.temperature)}°</strong><span>{data.condition}<small>Ощущается как {Math.round(data.feels_like)}°</small></span></div>
          <div className="weather-meta"><span>Влажность {data.humidity}%</span><span>Ветер {data.wind_speed} м/с</span><span>{data.pressure} гПа</span></div>
          <div className="forecast-row">{data.forecast.slice(0, 3).map((day) => <span key={day.date}>{day.date}<b>{Math.round(day.temp_max)}° / {Math.round(day.temp_min)}°</b></span>)}</div>
        </>
      )}
    </article>
  );
}

function NewsWidget() {
  const { data, error, loading } = useApi<NewsData>('/api/widget/news?limit=4&theme=dark');
  return (
    <article className="live-widget news-widget">
      <header><Newspaper size={18} /><h3>Последние события</h3><span>LIVE</span></header>
      <WidgetState loading={loading} error={error} />
      {data && !loading && !error && (
        <div className="news-list">
          {data.items.length === 0 && <p className="widget-empty">Событий пока нет. Радар продолжает проверять источники.</p>}
          {data.items.map((item) => {
            const content = <><time>{new Date(item.published_at).toLocaleString('ru-RU', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' })}</time><strong>{item.title}</strong><small>{item.source}</small></>;
            return item.url
              ? <a key={item.id} href={item.url} target="_blank" rel="noreferrer noopener">{content}</a>
              : <div key={item.id}>{content}</div>;
          })}
        </div>
      )}
    </article>
  );
}

function DangerWidget({ location, waiting, onLocate }: {
  location: LocationData | null; waiting: boolean; onLocate: () => void;
}) {
  const url = location
    ? `/api/widget/danger?city=${encodeURIComponent(location.city)}&theme=dark&lat=${location.latitude}&lon=${location.longitude}`
    : waiting ? null : '/api/widget/danger?city=auto&theme=dark';
  const [dangerUrl, setDangerUrl] = useState<string | null>(url);
  useEffect(() => setDangerUrl(url), [url]);
  const { data, error, loading } = useApi<DangerData>(dangerUrl);
  const locate = () => {
    if (!navigator.geolocation) return;
    navigator.geolocation.getCurrentPosition((position) => {
      setDangerUrl(`/api/widget/danger?theme=dark&lat=${position.coords.latitude}&lon=${position.coords.longitude}`);
      onLocate();
    }, () => setDangerUrl(url), { timeout: 7000 });
  };
  const started = data?.started_at
    ? new Date(data.started_at).toLocaleString('ru-RU', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' })
    : null;
  return (
    <article className={`live-widget danger-widget ${data?.active ? 'danger-active' : ''}`}>
      <header><ShieldAlert size={18} /><h3>Статус опасности</h3><button onClick={locate} aria-label="Определить опасность по точной геолокации"><MapPin size={15} /></button><span>24H</span></header>
      <WidgetState loading={loading} error={error} />
      {data && !loading && !error && (
        <div className="danger-status">
          <i />
          <strong>{data.active ? data.label || data.message : 'Опасность не обнаружена'}</strong>
          {data.active && data.message ? <p>{data.message}</p> : null}
          {data.active && started ? <p><small>Последнее событие: {started}{data.area ? ` · ${data.area}` : ''}</small></p> : null}
          {!data.active && <p>По данным подключённых источников за последние сутки{location ? ` · ${location.city}` : ''}.</p>}
        </div>
      )}
    </article>
  );
}

export default function LiveWidgets() {
  const [ipLocation, setIpLocation] = useState<LocationData | null>(null);
  const [locating, setLocating] = useState(false);
  const [ipError, setIpError] = useState('');
  const [ipLoading, setIpLoading] = useState(true);

  const applyLocation = useCallback((loc: LocationData) => {
    setIpLocation(loc);
    setIpError('');
  }, []);

  // Шаг 1: определяем город по IP.
  useEffect(() => {
    let cancelled = false;
    setIpLoading(true);
    setIpError('');
    fetch('/api/widget/location', { headers: { Accept: 'application/json' } })
      .then(async (response) => {
        const payload = await response.json() as LocationData & { message?: string };
        if (!response.ok) throw new Error(payload.message || 'Не удалось определить город по IP');
        return payload;
      })
      .then((loc) => { if (!cancelled) applyLocation(loc); })
      .catch((reason: Error) => { if (!cancelled) setIpError(reason.message); })
      .finally(() => { if (!cancelled) setIpLoading(false); });
    return () => { cancelled = true; };
  }, [applyLocation]);

  // Шаг 2 (по запросу или когда IP не дал город): точная геолокация браузера.
  const locateByBrowser = useCallback(() => {
    if (!navigator.geolocation) return;
    setLocating(true);
    navigator.geolocation.getCurrentPosition(async (position) => {
      const lat = position.coords.latitude;
      const lon = position.coords.longitude;
      try {
        const response = await fetch(`/api/widget/reverse?lat=${lat}&lon=${lon}`, { headers: { Accept: 'application/json' } });
        const payload = await response.json() as LocationData & { message?: string };
        if (!response.ok) throw new Error(payload.message || 'Не удалось определить город');
        applyLocation(payload);
      } catch (reason) {
        // Геокодер не дал город — всё равно показываем погоду/опасность по координатам.
        applyLocation({
          ok: true,
          city: 'по геолокации',
          region: '',
          country: '',
          latitude: lat,
          longitude: lon,
          approximate: true,
        });
      } finally {
        setLocating(false);
      }
    }, () => setLocating(false), { timeout: 7000 });
  }, [applyLocation]);

  return (
    <section className="live-section" id="live">
      <div className="section-heading"><h2>Сейчас в вашем городе</h2><p>Радар определит локацию по IP, а при разрешённой геолокации — по точным координатам, и покажет погоду и статус опасности рядом с вами.</p></div>
      <div className="live-grid">
        <LocationWidget data={ipLocation} error={ipError} loading={ipLoading || locating} onLocate={locateByBrowser} />
        <WeatherWidget location={ipLocation} waiting={ipLoading} onLocate={locateByBrowser} />
        <NewsWidget />
        <DangerWidget location={ipLocation} waiting={ipLoading} onLocate={locateByBrowser} />
      </div>
    </section>
  );
}
