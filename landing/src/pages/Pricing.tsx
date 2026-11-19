import PageLayout from '../components/PageLayout';
import { Check } from 'lucide-react';

export default function Pricing() {
  return (
    <PageLayout>
      <div className="pricing-page">
        <header className="page-title">
          <p className="update-date">Обновлено: ноябрь 2026</p>
          <h1>Тарифы и цены</h1>
          <p className="page-subtitle">
            Оповещения бесплатно навсегда. Актуальные тарифы подписки и порядок оформления
          </p>
        </header>

        <section className="intro-section">
          <p>
            <strong>Радар v5.11.5</strong> — честные цены, без скрытых платежей. 
            Все оповещения об угрозах — <strong>бесплатно навсегда</strong>.
          </p>
          <p>
            Подписка на подборки оплачивается через Telegram Stars. Способы оплаты 
            аренды приватного сервера и итоговая сумма показываются в боте до подтверждения заказа.
          </p>
        </section>

        <section className="pricing-grid">
          <div className="pricing-card free">
            <div className="card-icon">🛡</div>
            <h3>Оповещения об угрозах</h3>
            <div className="price">
              <span className="amount">0 ₽</span>
              <span className="period">бесплатно навсегда</span>
            </div>
            <ul className="features">
              <li><Check size={16} /> БПЛА / ракетная опасность / воздушная тревога / отбой</li>
              <li><Check size={16} /> МЧС: ЧС, штормовые предупреждения, эвакуация</li>
              <li><Check size={16} /> ЖКХ: вода, свет, газ, отопление — адресно</li>
              <li><Check size={16} /> Базовая погода (текст): текущая, 8 ч, 3 дня</li>
              <li><Check size={16} /> Проверка ссылок — 200/сутки</li>
              <li><Check size={16} /> ИИ-ассистент — базовый лимит</li>
              <li><Check size={16} /> Без рекламы, без трекинга</li>
            </ul>
            <a href="https://t.me/SecretHeroBot" target="_blank" rel="noreferrer noopener" className="cta-button">
              Запустить бота
            </a>
          </div>

          <div className="pricing-card">
            <div className="card-icon">📰</div>
            <h3>Новостные подборки</h3>
            <div className="price">
              <span className="amount">10 ⭐</span>
              <span className="period">30 дней</span>
            </div>
            <ul className="features">
              <li><Check size={16} /> 18 тематик в одной подписке</li>
              <li><Check size={16} /> ИИ-сводки и доставка по расписанию</li>
              <li><Check size={16} /> Погода картинкой</li>
              <li><Check size={16} /> Скачивание видео без дневного лимита подписчика</li>
            </ul>
            <a href="https://t.me/SecretHeroBot" target="_blank" rel="noreferrer noopener" className="cta-button">
              Оформить в боте за Stars
            </a>
          </div>

          <div className="pricing-card">
            <div className="card-icon">📰</div>
            <h3>Новостные подборки</h3>
            <div className="price">
              <span className="amount">25 ⭐</span>
              <span className="period">90 дней</span>
            </div>
            <ul className="features">
              <li><Check size={16} /> 18 тематик в одной подписке</li>
              <li><Check size={16} /> ИИ-сводки и доставка по расписанию</li>
              <li><Check size={16} /> Погода картинкой</li>
              <li><Check size={16} /> Скачивание видео без дневного лимита подписчика</li>
            </ul>
            <a href="https://t.me/SecretHeroBot" target="_blank" rel="noreferrer noopener" className="cta-button">
              Оформить в боте за Stars
            </a>
          </div>

          <div className="pricing-card">
            <div className="card-icon">📰</div>
            <h3>Новостные подборки</h3>
            <div className="price">
              <span className="amount">45 ⭐</span>
              <span className="period">180 дней</span>
            </div>
            <ul className="features">
              <li><Check size={16} /> 18 тематик в одной подписке</li>
              <li><Check size={16} /> ИИ-сводки и доставка по расписанию</li>
              <li><Check size={16} /> Погода картинкой</li>
              <li><Check size={16} /> Скачивание видео без дневного лимита подписчика</li>
            </ul>
            <a href="https://t.me/SecretHeroBot" target="_blank" rel="noreferrer noopener" className="cta-button">
              Оформить в боте за Stars
            </a>
          </div>

          <div className="pricing-card">
            <div className="card-icon">📰</div>
            <h3>Новостные подборки</h3>
            <div className="price">
              <span className="amount">85 ⭐</span>
              <span className="period">365 дней</span>
            </div>
            <ul className="features">
              <li><Check size={16} /> 18 тематик в одной подписке</li>
              <li><Check size={16} /> ИИ-сводки и доставка по расписанию</li>
              <li><Check size={16} /> Погода картинкой</li>
              <li><Check size={16} /> Скачивание видео без дневного лимита подписчика</li>
            </ul>
            <a href="https://t.me/SecretHeroBot" target="_blank" rel="noreferrer noopener" className="cta-button">
              Оформить в боте за Stars
            </a>
          </div>

          <div className="pricing-card">
            <div className="card-icon">🔐</div>
            <h3>Аренда приватного сервера</h3>
            <div className="price">
              <span className="amount">Тарифы в боте</span>
              <span className="period">срок и цена до оплаты</span>
            </div>
            <ul className="features">
              <li><Check size={16} /> Аренда приватного сервера</li>
              <li><Check size={16} /> Срок, трафик и число устройств зависят от тарифа</li>
              <li><Check size={16} /> Управление заказом в боте</li>
            </ul>
            <a href="https://t.me/SecretHeroBot" target="_blank" rel="noreferrer noopener" className="cta-button">
              Узнать тарифы в боте
            </a>
          </div>
        </section>

        <section className="notes-section">
          <p><strong>Важные замечания:</strong></p>
          <ul>
            <li>Цены подписки указаны в Telegram Stars (⭐); стоимость аренды сервера показывается в выбранном тарифе.</li>
            <li>Приватный сервер предоставляется для законного использования по назначению.</li>
            <li>Подписка на подборки оплачивается Stars; доступные способы оплаты аренды зависят от настроек бота.</li>
            <li>Возврат средств: заявка в поддержку в течение 14 дней, если сервис не предоставлен.</li>
            <li>Сам-хостинг (установка на свой сервер) — полностью бесплатно, код открыт (GPL-3.0).</li>
          </ul>
        </section>

        <section className="comparison-section">
          <h2>Сравнение: бесплатно vs подписка</h2>
          <table className="comparison-table">
            <thead>
              <tr>
                <th>Функция</th>
                <th>Бесплатно</th>
                <th>Подписка (Stars)</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>Тревоги БПЛА / МЧС / ЖКХ</td>
                <td>✅ Полностью</td>
                <td>✅ Полностью</td>
              </tr>
              <tr>
                <td>Погода (текст)</td>
                <td>✅ Текущая, 8ч, 3 дня</td>
                <td>✅ + картинка, вектор ветра, луна</td>
              </tr>
              <tr>
                <td>Новостные подборки</td>
                <td>❌</td>
                <td>✅ 18 тем, ИИ-сводки, расписание</td>
              </tr>
              <tr>
                <td>Проверка ссылок</td>
                <td>200/сутки</td>
                <td>Без лимита</td>
              </tr>
              <tr>
                <td>ИИ-ассистент</td>
                <td>Базовый лимит</td>
                <td>Расширенный лимит</td>
              </tr>
              <tr>
                <td>Аренда приватного сервера</td>
                <td>❌</td>
                <td>Отдельно (₽)</td>
              </tr>
            </tbody>
          </table>
        </section>

        <section className="how-to-pay">
          <h2>Как оплатить</h2>
          <ol>
            <li>Откройте бота: <a href="https://t.me/SecretHeroBot" target="_blank" rel="noreferrer noopener">@SecretHeroBot</a></li>
            <li>Меню → «Подписки» или «Сервер»</li>
            <li>Выберите тариф и один из доступных способов оплаты</li>
            <li>Доступ активируется автоматически</li>
          </ol>
          <p>Вопросы по оплате? <a href="/support">Напишите в поддержку</a></p>
        </section>
      </div>
    </PageLayout>
  );
}
