const routeMeta = {
  dashboard: ["защищенный контур", "ZAJ BANK"],
  accounts: ["личный кабинет", "Счета"],
  transfer: ["операции", "Переводы"],
  payments: ["городские сервисы", "Платежи"],
  programs: ["государство → банк → граждане", "Госпрограммы"],
  market: ["zaj market", "Маркет"],
  history: ["операции", "История"],
  security: ["контроль доступа", "Защита"],
};

const sectionFiles = {
  dashboard: "dashboard.html",
  accounts: "accounts.html",
  transfer: "transfer.html",
  payments: "payments.html",
  programs: "programs.html",
  market: "market.html",
  history: "history.html",
  security: "security.html",
};

const marketProducts = [
  {
    title: "ZAJ Phone X",
    category: "Смартфоны",
    price: 389_990,
    tag: "рассрочка 0%",
    accent: "cyan",
  },
  {
    title: "Ноутбук Atlas 14",
    category: "Техника",
    price: 549_000,
    tag: "для учебы",
    accent: "blue",
  },
  {
    title: "Наушники Pulse Air",
    category: "Аудио",
    price: 49_900,
    tag: "кэшбэк",
    accent: "gold",
  },
  {
    title: "Умные часы Nomad",
    category: "Гаджеты",
    price: 119_000,
    tag: "новинка",
    accent: "clay",
  },
  {
    title: "Электросамокат City",
    category: "Транспорт",
    price: 219_500,
    tag: "город",
    accent: "cyan",
  },
  {
    title: "Пылесос Home Pro",
    category: "Дом",
    price: 87_400,
    tag: "быстрая доставка",
    accent: "gold",
  },
];

const state = {
  user: null,
  dashboard: null,
  smsChallenge: null,
  loginChallenge: null,
  authMode: "login",
};

const page = document.body.dataset.page;
const section = document.body.dataset.section || "dashboard";
const toast = document.querySelector(".toast");

initBackButton();

if (page === "home") initHomePage();
if (page === "login") initLoginPage();
if (page === "register") initRegisterPage();
if (page === "private") initPrivatePage(section);

function initBackButton() {
  document.querySelectorAll("[data-back-button]").forEach((button) => {
    button.addEventListener("click", () => {
      const fallback = button.dataset.backFallback || "index.html";
      if (history.length > 1) history.back();
      else location.href = fallback;
    });
  });
}

function initHomePage() {
  document.querySelectorAll("[data-private-link]").forEach((element) => {
    element.addEventListener("click", () => guardedNavigate(element.dataset.privateLink));
  });

  document.querySelectorAll("[data-scroll-target]").forEach((element) => {
    element.addEventListener("click", () => {
      document.querySelector(element.dataset.scrollTarget)?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  });

  document.querySelector("#searchForm")?.addEventListener("submit", (event) => {
    event.preventDefault();
    const query = document.querySelector("#searchInput")?.value.trim().toLowerCase() || "";
    if (query.includes("счет") || query.includes("баланс")) guardedNavigate("accounts.html");
    else if (query.includes("перев")) guardedNavigate("transfer.html");
    else if (query.includes("плат") || query.includes("жкх") || query.includes("налог")) guardedNavigate("payments.html");
    else if (query.includes("гос") || query.includes("выплат")) guardedNavigate("programs.html");
    else if (query.includes("истор") || query.includes("операц")) guardedNavigate("history.html");
    else if (query.includes("защит") || query.includes("безопас")) guardedNavigate("security.html");
    else if (query.includes("маркет") || query.includes("товар") || query.includes("покуп")) guardedNavigate("market.html");
    else {
      filterMarket(query);
      document.querySelector("#market")?.scrollIntoView({ behavior: "smooth", block: "start" });
      showToast(query ? "Показал товары по запросу" : "Введите название сервиса или товара");
    }
  });

  document.querySelector("#marketSearchForm")?.addEventListener("submit", (event) => {
    event.preventDefault();
    filterMarket(document.querySelector("#marketSearchInput")?.value || "");
  });

  document.querySelector("#marketSearchInput")?.addEventListener("input", (event) => {
    filterMarket(event.currentTarget.value);
  });

  renderMarketProducts(marketProducts);
}

function initLoginPage() {
  initAuthTabs();
  document.querySelector("#loginForm")?.addEventListener("submit", handleLogin);
  document.querySelector("#registerForm")?.addEventListener("submit", handleRegister);
}

function initRegisterPage() {
  const next = new URLSearchParams(location.search).get("next");
  const target = new URL("login.html", location.href);
  target.searchParams.set("mode", "register");
  if (next) target.searchParams.set("next", next);
  location.replace(`${target.pathname.split("/").pop()}${target.search}`);
}

async function initPrivatePage(route) {
  try {
    const data = await api("/me");
    state.user = data.user;
    state.dashboard = data.dashboard;
    updatePrivateChrome(route);
    renderPrivateRoute(route);
  } catch (error) {
    location.href = `login.html?next=${encodeURIComponent(currentFile())}`;
  }
}

async function guardedNavigate(path) {
  try {
    await api("/me");
    location.href = path;
  } catch (error) {
    location.href = `login.html?next=${encodeURIComponent(path)}`;
  }
}

function initAuthTabs() {
  const requestedMode = new URLSearchParams(location.search).get("mode");
  setAuthMode(requestedMode === "register" ? "register" : "login", false);

  document.querySelectorAll("[data-auth-tab], [data-auth-switch]").forEach((button) => {
    button.addEventListener("click", () => setAuthMode(button.dataset.authTab || button.dataset.authSwitch));
  });
}

function setAuthMode(mode, updateUrl = true) {
  state.authMode = mode === "register" ? "register" : "login";
  document.querySelectorAll("[data-auth-tab]").forEach((button) => {
    button.classList.toggle("is-active", button.dataset.authTab === state.authMode);
  });
  document.querySelector("#loginForm")?.classList.toggle("is-active", state.authMode === "login");
  document.querySelector("#registerForm")?.classList.toggle("is-active", state.authMode === "register");

  const intent = document.querySelector("[data-auth-intent] span");
  if (intent) {
    intent.textContent =
      state.authMode === "register"
        ? "Укажите имя и телефон, затем подтвердите номер SMS-кодом."
        : "Введите телефон, получите SMS-код и откройте личный кабинет.";
  }

  if (updateUrl) {
    const params = new URLSearchParams(location.search);
    if (state.authMode === "register") params.set("mode", "register");
    else params.delete("mode");
    const query = params.toString();
    history.replaceState(null, "", `${currentFile()}${query ? `?${query}` : ""}`);
  }
}

async function handleLogin(event) {
  event.preventDefault();
  const form = new FormData(event.currentTarget);

  try {
    if (!state.loginChallenge) {
      const data = await api("/login/start", {
        method: "POST",
        body: {
          phone: form.get("phone"),
        },
      });
      state.loginChallenge = data.challengeId;
      document.querySelector("#loginSmsStep").hidden = false;
      document.querySelector("#loginSubmit").innerHTML =
        '<svg><use href="icons.svg#icon-check"></use></svg>Подтвердить вход';
      document.querySelector("[data-login-sms-hint]").textContent =
        data.demoCode ? `SMS-код отправлен. Для локального демо код: ${data.demoCode}` : "SMS-код отправлен.";
      showToast("SMS-код отправлен на телефон");
      return;
    }

    await api("/login/verify", {
      method: "POST",
      body: {
        challengeId: state.loginChallenge,
        code: form.get("smsCode"),
      },
    });
    location.href = nextPath();
  } catch (error) {
    showToast(error.message);
  }
}

async function handleRegister(event) {
  event.preventDefault();
  const form = new FormData(event.currentTarget);

  try {
    if (!state.smsChallenge) {
      const data = await api("/register/start", {
        method: "POST",
        body: {
          name: form.get("name"),
          phone: form.get("phone"),
        },
      });
      state.smsChallenge = data.challengeId;
      document.querySelector("#registerSmsStep").hidden = false;
      document.querySelector("#registerSubmit").innerHTML =
        '<svg><use href="icons.svg#icon-check"></use></svg>Подтвердить и создать';
      document.querySelector("[data-sms-hint]").textContent =
        data.demoCode ? `SMS-код отправлен. Для локального демо код: ${data.demoCode}` : "SMS-код отправлен.";
      showToast("SMS-код отправлен на телефон");
      return;
    }

    await api("/register/verify", {
      method: "POST",
      body: {
        challengeId: state.smsChallenge,
        code: form.get("smsCode"),
      },
    });
    location.href = nextPath();
  } catch (error) {
    showToast(error.message);
  }
}

function updatePrivateChrome(route) {
  const [kicker, title] = routeMeta[route] || routeMeta.dashboard;
  const pageKicker = document.querySelector("[data-page-kicker]");
  const pageTitle = document.querySelector("[data-page-title]");
  const profileLetter = document.querySelector("[data-profile-letter]");
  if (pageKicker) pageKicker.textContent = kicker;
  if (pageTitle) pageTitle.textContent = title;
  if (profileLetter && state.user?.name) profileLetter.textContent = state.user.name.slice(0, 1).toUpperCase();

  document.querySelector("#logoutButton")?.addEventListener("click", handleLogout);
  document.querySelector("#privacyToggle")?.addEventListener("click", () => {
    document.body.classList.toggle("privacy-mask");
    showToast(document.body.classList.contains("privacy-mask") ? "Суммы скрыты" : "Суммы снова видны");
  });

  document.querySelector("#searchForm")?.addEventListener("submit", (event) => {
    event.preventDefault();
    const query = document.querySelector("#searchInput").value.trim().toLowerCase();
    if (query.includes("счет") || query.includes("баланс")) location.href = "accounts.html";
    else if (query.includes("перев")) location.href = "transfer.html";
    else if (query.includes("плат") || query.includes("жкх") || query.includes("налог")) location.href = "payments.html";
    else if (query.includes("гос") || query.includes("выплат")) location.href = "programs.html";
    else if (query.includes("истор") || query.includes("операц")) location.href = "history.html";
    else if (query.includes("защит") || query.includes("безопас")) location.href = "security.html";
    else if (query.includes("маркет") || query.includes("товар") || query.includes("покуп")) location.href = "market.html";
    else showToast("Поиск работает по разделам: счета, переводы, платежи, госпрограммы, маркет, история, защита");
  });
}

async function handleLogout() {
  try {
    await api("/logout", { method: "POST" });
  } catch (error) {
    // The local page should leave the private area even if the session has expired.
  }
  location.href = "index.html";
}

function renderPrivateRoute(route) {
  const view = document.querySelector("#privateView");
  if (!view || !state.dashboard) return;
  if (route === "accounts") view.innerHTML = renderAccounts();
  else if (route === "transfer") view.innerHTML = renderTransfer();
  else if (route === "payments") view.innerHTML = renderPayments();
  else if (route === "programs") view.innerHTML = renderPrograms();
  else if (route === "market") view.innerHTML = renderMarket();
  else if (route === "history") view.innerHTML = renderHistory();
  else if (route === "security") view.innerHTML = renderSecurity();
  else view.innerHTML = renderDashboard();

  bindRenderedActions(route);
}

function renderDashboard() {
  const primary = state.dashboard.accounts[0];
  const total = state.dashboard.accounts.reduce((sum, account) => sum + Number(account.balance || 0), 0);
  const actions = [
    ["accounts.html", "icon-wallet", "Счета", "Баланс и отдельные банковские счета"],
    ["transfer.html", "icon-transfer", "Переводы", "Отправка денег получателю"],
    ["payments.html", "icon-receipt", "Платежи", "Налоги, ЖКХ, школа и транспорт"],
    ["programs.html", "icon-building", "Госпрограммы", "Выплаты, льготы и субсидии"],
    ["market.html", "icon-market", "Маркет", "Каталог товаров и оплата со счета"],
    ["history.html", "icon-receipt", "История", "Все операции и заказы"],
    ["security.html", "icon-shield", "Защита", "Контроль сессии и данных"],
  ];
  return `
    <div class="hero-grid">
      <article class="panel panel-pad">
        <div class="panel-heading">
          <div>
            <p class="eyebrow">общий баланс</p>
            <p class="balance-value money">${money(total)}</p>
          </div>
          <span class="badge">SMS проверен</span>
        </div>
        ${chart(["42%", "68%", "51%", "78%", "62%", "90%"])}
        <div class="metric-list">
          <div><small>Основной счет</small><strong class="money">${money(primary.balance)}</strong></div>
          <div><small>Счетов</small><strong>${state.dashboard.accounts.length}</strong></div>
          <div><small>Кэшбэк</small><strong class="money">${money(state.dashboard.accounts.reduce((sum, account) => sum + Number(account.cashback || 0), 0))}</strong></div>
        </div>
      </article>

      <article class="panel-dark visual-panel">
        <div class="brand-visual is-compact" aria-hidden="true">
          <span class="brand-visual-card"></span>
          <span class="brand-visual-line"></span>
          <span class="brand-visual-chip"></span>
        </div>
        <div class="visual-copy">
          <p class="eyebrow">цифровой маршрут</p>
          <h2>Государственные выплаты и банковские операции в закрытом кабинете.</h2>
        </div>
      </article>

      <article class="panel panel-pad">
        <div class="panel-heading">
          <div>
            <p class="eyebrow">личный кабинет</p>
            <h2>Каждая функция отдельно</h2>
          </div>
          <svg><use href="icons.svg#icon-home"></use></svg>
        </div>
        <p class="muted-copy">Дашборд показывает только обзор. Для действий открывайте отдельную страницу.</p>
        <a class="primary-button" href="accounts.html">
          <svg><use href="icons.svg#icon-wallet"></use></svg>
          Перейти к счетам
        </a>
      </article>
    </div>

    <div class="function-grid">
      ${actions
        .map(
          ([href, icon, title, text]) => `
            <a class="function-card panel" href="${href}">
              <span class="feature-icon"><svg><use href="icons.svg#${icon}"></use></svg></span>
              <strong>${title}</strong>
              <small>${text}</small>
            </a>
          `,
        )
        .join("")}
    </div>
  `;
}

function renderAccounts() {
  return `
    <div class="route-head">
      <div>
        <p class="eyebrow">закрытые данные</p>
        <h2 class="route-title">Ваши счета</h2>
        <p>Баланс и движения средств отображаются только в активной сессии.</p>
      </div>
    </div>
    <div class="accounts-grid">
      ${state.dashboard.accounts
        .map(
          (account) => `
            <article class="account-card">
              <div class="account-top">
                <div>
                  <small>${escapeHtml(account.name)}</small>
                  <strong class="money">${money(account.balance)}</strong>
                </div>
                <svg><use href="icons.svg#icon-wallet"></use></svg>
              </div>
              <div class="metric-list">
                <div><small>Поступления</small><b class="money">+ ${money(account.income)}</b></div>
                <div><small>Платежи</small><b class="money">- ${money(account.spending)}</b></div>
                <div><small>Кэшбэк</small><b class="money">${money(account.cashback)}</b></div>
              </div>
            </article>
          `,
        )
        .join("")}
    </div>
  `;
}

function renderTransfer() {
  return `
    <div class="route-head">
      <div>
        <p class="eyebrow">операции</p>
        <h2 class="route-title">Новый перевод</h2>
        <p>После отправки операция сохраняется в SQLite и сразу появляется в истории.</p>
      </div>
    </div>
    <div class="hero-grid">
      <article class="panel panel-pad">
        <form class="transfer-form" id="transferForm">
          <label>
            Получатель
            <input name="recipient" type="text" placeholder="ИИН, телефон или имя" autocomplete="off" required />
          </label>
          <label>
            Сумма
            <input name="amount" type="number" min="500" step="100" placeholder="₸ 0" required />
          </label>
          <label>
            Счет списания
            <select name="source">
              ${state.dashboard.accounts.map((account) => `<option value="${account.slug}">${escapeHtml(account.name)}</option>`).join("")}
            </select>
          </label>
          <button class="primary-button" type="submit">
            <svg><use href="icons.svg#icon-send"></use></svg>
            Отправить
          </button>
        </form>
      </article>
      <article class="panel panel-pad">
        <p class="eyebrow">переводы</p>
        <h2>Только отправка денег</h2>
        <p class="muted-copy">История операций вынесена на отдельную страницу, чтобы раздел переводов оставался чистым.</p>
        <a class="ghost-button" href="history.html">Открыть историю</a>
      </article>
      <article class="panel panel-pad security-panel">
        <p class="eyebrow">контроль</p>
        <h2>Переводы требуют входа</h2>
        <p>Если пользователь нажмет перевод без авторизации, сайт отправит его на отдельную страницу входа.</p>
        <div class="security-score" aria-label="Уровень контроля">
          <span style="--score: 94%"></span>
        </div>
      </article>
    </div>
  `;
}

function renderPayments() {
  return `
    <div class="route-head">
      <div>
        <p class="eyebrow">городские сервисы</p>
        <h2 class="route-title">Платежи</h2>
        <p>Оплачивайте налоги, ЖКХ, школу и транспорт с выбранного банковского счета.</p>
      </div>
    </div>
    <div class="hero-grid">
      <article class="panel panel-pad">
        <form class="transfer-form" id="paymentForm">
          <label>
            Услуга
            <select name="service">
              <option value="Налоги">Налоги</option>
              <option value="ЖКХ">ЖКХ</option>
              <option value="Школа">Школа</option>
              <option value="Транспорт">Транспорт</option>
            </select>
          </label>
          <label>
            Сумма
            <input name="amount" type="number" min="300" step="100" placeholder="₸ 0" required />
          </label>
          <label>
            Счет списания
            <select name="source">
              ${state.dashboard.accounts.map((account) => `<option value="${account.slug}">${escapeHtml(account.name)} · ${money(account.balance)}</option>`).join("")}
            </select>
          </label>
          <button class="primary-button" type="submit">
            <svg><use href="icons.svg#icon-receipt"></use></svg>
            Оплатить
          </button>
        </form>
      </article>
      ${servicesPanel()}
      <article class="panel panel-pad security-panel">
        <p class="eyebrow">контроль</p>
        <h2>Платежи сохраняются</h2>
        <p>После оплаты операция появляется на отдельной странице истории.</p>
        <div class="security-score"><span style="--score: 89%"></span></div>
      </article>
    </div>
  `;
}

function renderPrograms() {
  return `
    <div class="route-head">
      <div>
        <p class="eyebrow">государство → банк → граждане</p>
        <h2 class="route-title">Госпрограммы</h2>
        <p>Выплаты, льготы и субсидии видны только владельцу кабинета.</p>
      </div>
    </div>
    <div class="content-grid">
      ${programsPanel()}
      <article class="panel-dark visual-panel">
        <div class="brand-visual is-compact" aria-hidden="true">
          <span class="brand-visual-card"></span>
          <span class="brand-visual-line"></span>
          <span class="brand-visual-chip"></span>
        </div>
        <div class="visual-copy">
          <p class="eyebrow">маршрут выплат</p>
          <h2>Средства проходят через банк и доходят до гражданина в кабинете.</h2>
        </div>
      </article>
    </div>
  `;
}

function renderMarket() {
  const selectedProduct = new URLSearchParams(location.search).get("product");
  return `
    <div class="route-head">
      <div>
        <p class="eyebrow">zaj market</p>
        <h2 class="route-title">Каталог и покупки</h2>
        <p>Товары оплачиваются с выбранного банковского счета, заказ и списание сразу сохраняются в SQLite.</p>
      </div>
    </div>
    <section class="panel panel-pad market-paybar">
      <div>
        <p class="eyebrow">оплата</p>
        <h2>Выберите счет для покупок</h2>
      </div>
      <label>
        Счет списания
        <select id="marketSource">
          ${state.dashboard.accounts.map((account) => `<option value="${account.slug}">${escapeHtml(account.name)} · ${money(account.balance)}</option>`).join("")}
        </select>
      </label>
    </section>
    <div class="market-grid is-private">
      ${marketProducts
        .map(
          (product) => `
            <article class="market-card ${selectedProduct === product.title ? "is-selected" : ""}">
              <div class="product-art ${product.accent}">
                <svg><use href="icons.svg#icon-market"></use></svg>
              </div>
              <small>${escapeHtml(product.category)} · ${escapeHtml(product.tag)}</small>
              <h3>${escapeHtml(product.title)}</h3>
              <div class="market-card-bottom">
                <strong>${money(product.price)}</strong>
                <button class="primary-button" type="button" data-private-market-buy="${escapeHtml(product.title)}">
                  <svg><use href="icons.svg#icon-check"></use></svg>
                  Купить
                </button>
              </div>
            </article>
          `,
        )
        .join("")}
    </div>
    <div class="content-grid">
      ${ordersPanel()}
      <article class="panel panel-pad security-panel">
        <p class="eyebrow">контроль</p>
        <h2>Покупки проходят через счет</h2>
        <p>Если денег недостаточно, ZAJ BANK не проведет операцию и покажет ошибку.</p>
        <div class="security-score"><span style="--score: 91%"></span></div>
      </article>
    </div>
  `;
}

function renderHistory() {
  return `
    <div class="route-head">
      <div>
        <p class="eyebrow">операции и заказы</p>
        <h2 class="route-title">История</h2>
        <p>Все движения денег и покупки собраны на отдельной странице.</p>
      </div>
    </div>
    <div class="content-grid">
      ${activityPanel()}
      ${ordersPanel()}
      <article class="panel panel-pad">
        <p class="eyebrow">сводка</p>
        <h2>Контроль расходов</h2>
        <div class="metric-list">
          <div><small>Операций</small><strong>${state.dashboard.transactions.length}</strong></div>
          <div><small>Заказов</small><strong>${(state.dashboard.orders || []).length}</strong></div>
          <div><small>Общий кэшбэк</small><strong class="money">${money(state.dashboard.accounts.reduce((sum, account) => sum + Number(account.cashback || 0), 0))}</strong></div>
        </div>
      </article>
    </div>
  `;
}

function renderSecurity() {
  return `
    <div class="route-head">
      <div>
        <p class="eyebrow">контроль доступа</p>
        <h2 class="route-title">Защита</h2>
        <p>Личные данные не показываются до входа, сессия хранится в HttpOnly cookie, пароли хранятся как PBKDF2-хэш.</p>
      </div>
    </div>
    <div class="content-grid">
      <article class="panel panel-pad security-panel">
        <p class="eyebrow">уровень защиты</p>
        <h2>Спокойный режим</h2>
        <p>Скрытие сумм, закрытые разделы и локальное хранение данных включены.</p>
        <div class="security-score"><span style="--score: 96%"></span></div>
      </article>
      <article class="panel panel-pad">
        <p class="eyebrow">база данных</p>
        <h2>SQLite локально</h2>
        <div class="metric-list">
          <div><small>Файл</small><strong>data/zaj_bank.sqlite3</strong></div>
          <div><small>Пользователь</small><strong>${escapeHtml(state.user.phone || state.user.email)}</strong></div>
          <div><small>Данные</small><strong>счета, выплаты, операции</strong></div>
        </div>
      </article>
      <article class="panel panel-pad">
        <p class="eyebrow">сессия</p>
        <h2>Доступ активен</h2>
        <p class="muted-copy">Выход удаляет локальную сессию. Следующий вход снова потребует телефон и SMS-код.</p>
        <button class="ghost-button" type="button" data-logout-action>Выйти</button>
      </article>
    </div>
  `;
}

function programsPanel() {
  return `
    <article class="panel panel-pad">
      <div class="panel-heading">
        <div>
          <p class="eyebrow">госпрограммы</p>
          <h2>Выплаты и льготы</h2>
        </div>
        <a class="ghost-button" href="programs.html">Все</a>
      </div>
      <ul class="program-list">
        ${state.dashboard.programs
          .map(
            (program, index) => `
              <li>
                <span class="program-icon ${["mint", "amber", "blue"][index % 3]}"><svg><use href="icons.svg#${index % 2 ? "icon-receipt" : "icon-check"}"></use></svg></span>
                <div>
                  <strong>${escapeHtml(program.title)}</strong>
                  <small>${escapeHtml(program.status)}</small>
                </div>
                <b class="money">${money(program.amount)}</b>
              </li>
            `,
          )
          .join("")}
      </ul>
    </article>
  `;
}

function servicesPanel() {
  return `
    <article class="panel panel-pad">
      <div class="panel-heading">
        <div>
          <p class="eyebrow">платежи</p>
          <h2>Городские сервисы</h2>
        </div>
      </div>
      <div class="service-grid">
        <button class="service-tile" type="button" data-service="Налоги"><svg><use href="icons.svg#icon-receipt"></use></svg><span>Налоги</span></button>
        <button class="service-tile" type="button" data-service="ЖКХ"><svg><use href="icons.svg#icon-building"></use></svg><span>ЖКХ</span></button>
        <button class="service-tile" type="button" data-service="Школа"><svg><use href="icons.svg#icon-wallet"></use></svg><span>Школа</span></button>
        <button class="service-tile" type="button" data-service="Транспорт"><svg><use href="icons.svg#icon-transfer"></use></svg><span>Транспорт</span></button>
      </div>
    </article>
  `;
}

function activityPanel() {
  return `
    <article class="panel panel-pad">
      <div class="panel-heading">
        <div>
          <p class="eyebrow">история</p>
          <h2>Последние операции</h2>
        </div>
      </div>
      <ul class="activity-list">
        ${state.dashboard.transactions
          .map(
            (item) => `
              <li>
                <span class="activity-mark ${item.direction}"></span>
                <div>
                  <strong>${escapeHtml(item.title)}</strong>
                  <small>${escapeHtml(item.subtitle)}</small>
                </div>
                <b class="money">${item.amount >= 0 ? "+" : "-"} ${money(Math.abs(item.amount))}</b>
              </li>
            `,
          )
          .join("")}
      </ul>
    </article>
  `;
}

function ordersPanel() {
  const orders = state.dashboard.orders || [];
  return `
    <article class="panel panel-pad">
      <div class="panel-heading">
        <div>
          <p class="eyebrow">маркет</p>
          <h2>Заказы</h2>
        </div>
        <a class="ghost-button" href="market.html">Каталог</a>
      </div>
      ${
        orders.length
          ? `<ul class="activity-list">
              ${orders
                .map(
                  (order) => `
                    <li>
                      <span class="activity-mark out"></span>
                      <div>
                        <strong>${escapeHtml(order.product_title)}</strong>
                        <small>${escapeHtml(order.status)} · ${escapeHtml(order.category)}</small>
                      </div>
                      <b class="money">- ${money(order.amount)}</b>
                    </li>
                  `,
                )
                .join("")}
            </ul>`
          : `<p class="muted-copy">Покупок пока нет. Каталог уже подключен к счетам и истории операций.</p>`
      }
    </article>
  `;
}

function filterMarket(value) {
  const query = String(value).trim().toLowerCase();
  const results = query
    ? marketProducts.filter((product) =>
        `${product.title} ${product.category} ${product.tag}`.toLowerCase().includes(query),
      )
    : marketProducts;
  renderMarketProducts(results);
}

function renderMarketProducts(products) {
  const grid = document.querySelector("#marketGrid");
  if (!grid) return;
  if (!products.length) {
    grid.innerHTML = `
      <article class="market-empty">
        <p class="eyebrow">ничего не найдено</p>
        <h3>Попробуйте другой товар</h3>
      </article>
    `;
    return;
  }
  grid.innerHTML = products
    .map(
      (product) => `
        <article class="market-card">
          <div class="product-art ${product.accent}">
            <svg><use href="icons.svg#icon-market"></use></svg>
          </div>
          <small>${escapeHtml(product.category)} · ${escapeHtml(product.tag)}</small>
          <h3>${escapeHtml(product.title)}</h3>
          <div class="market-card-bottom">
            <strong>${money(product.price)}</strong>
            <button class="ghost-button" type="button" data-market-buy="${escapeHtml(product.title)}">Купить</button>
          </div>
        </article>
      `,
    )
    .join("");

  document.querySelectorAll("[data-market-buy]").forEach((button) => {
    button.addEventListener("click", () => {
      guardedNavigate(`market.html?product=${encodeURIComponent(button.dataset.marketBuy)}`);
    });
  });
}

function bindRenderedActions(route) {
  document.querySelectorAll("[data-service]").forEach((button) => {
    button.addEventListener("click", () => showToast(`${button.dataset.service}: раздел готов к подключению`));
  });
  document.querySelector("[data-logout-action]")?.addEventListener("click", handleLogout);
  if (route === "transfer") {
    document.querySelector("#transferForm")?.addEventListener("submit", handleTransfer);
  }
  if (route === "payments") {
    document.querySelector("#paymentForm")?.addEventListener("submit", handlePayment);
  }
  if (route === "market") {
    document.querySelectorAll("[data-private-market-buy]").forEach((button) => {
      button.addEventListener("click", () => handleMarketBuy(button.dataset.privateMarketBuy));
    });
  }
}

async function handleTransfer(event) {
  event.preventDefault();
  const form = new FormData(event.currentTarget);
  try {
    const data = await api("/transfer", {
      method: "POST",
      body: {
        recipient: form.get("recipient"),
        amount: Number(form.get("amount")),
        source: form.get("source"),
      },
    });
    state.dashboard = data.dashboard;
    renderPrivateRoute("transfer");
    showToast("Перевод сохранен в базе данных");
  } catch (error) {
    showToast(error.message);
  }
}

async function handlePayment(event) {
  event.preventDefault();
  const form = new FormData(event.currentTarget);
  try {
    const data = await api("/service/pay", {
      method: "POST",
      body: {
        service: form.get("service"),
        amount: Number(form.get("amount")),
        source: form.get("source"),
      },
    });
    state.dashboard = data.dashboard;
    renderPrivateRoute("payments");
    showToast("Платеж сохранен в истории");
  } catch (error) {
    showToast(error.message);
  }
}

async function handleMarketBuy(product) {
  const source = document.querySelector("#marketSource")?.value || "personal";
  try {
    const data = await api("/market/buy", {
      method: "POST",
      body: {
        product,
        source,
      },
    });
    state.dashboard = data.dashboard;
    history.replaceState(null, "", "market.html");
    renderPrivateRoute("market");
    showToast("Покупка оплачена и сохранена в истории");
  } catch (error) {
    showToast(error.message);
  }
}

async function api(path, options = {}) {
  const response = await fetch(`/api${path}`, {
    method: options.method || "GET",
    headers: options.body ? { "Content-Type": "application/json" } : undefined,
    body: options.body ? JSON.stringify(options.body) : undefined,
    credentials: "same-origin",
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || "Ошибка запроса");
  return data;
}

function wireNextLinks() {
  document.querySelectorAll("[data-next-link]").forEach((link) => {
    const url = new URL(link.getAttribute("href"), location.href);
    const next = new URLSearchParams(location.search).get("next");
    if (next) url.searchParams.set("next", next);
    link.href = `${url.pathname.split("/").pop()}${url.search}`;
  });
}

function nextPath() {
  const next = new URLSearchParams(location.search).get("next");
  if (!next || next.startsWith("http") || next.startsWith("//")) return "dashboard.html";
  return next;
}

function currentFile() {
  return location.pathname.split("/").pop() || "dashboard.html";
}

function chart(values) {
  return `<div class="mini-chart" aria-label="Динамика баланса">${values.map((value) => `<span style="--value: ${value}"></span>`).join("")}</div>`;
}

function money(value) {
  return `₸ ${new Intl.NumberFormat("ru-RU").format(Math.round(value))}`;
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (char) => {
    const map = {
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#039;",
    };
    return map[char];
  });
}

function showToast(message) {
  if (!toast) return;
  toast.textContent = message;
  toast.classList.add("is-visible");
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => toast.classList.remove("is-visible"), 2800);
}
