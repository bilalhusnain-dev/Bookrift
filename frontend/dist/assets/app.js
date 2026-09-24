import { setupPhotos, clearPhoto, closeCamera, setPhotoBusy } from './photos.js';

const $ = (selector, parent = document) => parent.querySelector(selector);
const $$ = (selector, parent = document) => [...parent.querySelectorAll(selector)];

const state = {
  token: localStorage.getItem("bookrift_token") || "",
  user: null,
  catalogue: new Map(),
  library: new Map(),
  adminBooks: new Map(),
  adminFormDirty: false,
  toastTimer: null,
};

// Data ko HTML mein dikhane se pehle special characters escape karne hain.
function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function safeCover(url) {
  if (!url) return "";
  try {
    const parsed = new URL(url, window.location.origin);
    return ["http:", "https:"].includes(parsed.protocol) ? parsed.href : "";
  } catch {
    return "";
  }
}

// Har API request ke saath token; response aur errors yahin handle karne hain.
async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  if (state.token) headers.set("Authorization", `Bearer ${state.token}`);
  if (options.body && !(options.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }

  let response;
  try {
    response = await fetch(path, { ...options, headers });
  } catch {
    throw new Error("Cannot reach Bookrift. Check your connection and try again.");
  }
  let data;
  try {
    data = await response.json();
  } catch {
    throw new Error("Bookrift returned an unreadable response. Please try again shortly.");
  }
  if (!data || typeof data !== "object" || Array.isArray(data)) {
    throw new Error("Bookrift returned an unexpected response. Please try again shortly.");
  }
  if (!response.ok) {
    if (response.status === 401 && state.token) signOut(false);
    const error = new Error(data.error || "Something went wrong. Please try again.");
    error.status = response.status;
    throw error;
  }
  return data;
}

function saveToken(token) {
  state.token = token || "";
  if (state.token) localStorage.setItem("bookrift_token", state.token);
  else localStorage.removeItem("bookrift_token");
}

function showToast(message) {
  const toast = $("#toast");
  toast.textContent = message;
  toast.hidden = false;
  clearTimeout(state.toastTimer);
  state.toastTimer = setTimeout(() => {
    toast.hidden = true;
  }, 4000);
}

// App ke andar apna confirmation box dikhana.
function openConfirm(message, needPassword) {
  const dialog = $("#confirm-dialog");
  const password = $("#confirm-password");
  $("#confirm-message").textContent = message;
  password.value = "";
  password.hidden = !needPassword;
  $("#confirm-password-label").hidden = !needPassword;
  dialog.showModal();

  return new Promise((resolve) => {
    function finish(confirmed) {
      dialog.close();
      resolve(needPassword ? (confirmed ? password.value : "") : confirmed);
    }
    // Naya question aaye to purana click handler replace karna.
    $("#confirm-form").onsubmit = (event) => {
      event.preventDefault();
      finish(true);
    };
    $("#confirm-cancel").onclick = () => finish(false);
    dialog.oncancel = () => finish(false);
  });
}

function askConfirm(message) {
  return openConfirm(message, false);
}

function askPassword(message) {
  return openConfirm(message, true);
}

function setMessage(form, message = "", success = false) {
  const target = $("[data-form-message]", form);
  if (!target) return;
  target.textContent = message;
  target.classList.toggle("success", success);
}

function setBusy(form, busy, text = "Please wait...") {
  const button = $("button[type='submit']", form);
  if (!button) return;
  if (!button.dataset.label) button.dataset.label = button.textContent;
  button.disabled = busy;
  button.textContent = busy ? text : button.dataset.label;
}

function showAuthForm(name, openModal = true) {
  $$('[data-auth-form]').forEach((form) => {
    form.hidden = form.dataset.authForm !== name;
  });
  $$(".auth-tab").forEach((button) => {
    const active = button.dataset.authView === name;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", String(active));
  });
  if (openModal && !$("#welcome-view").hidden) {
    $("#auth-modal").hidden = false;
    document.body.classList.add("modal-open");
  }
  const firstInput = $(`[data-auth-form="${name}"] input`);
  if (openModal) firstInput?.focus();
}

function closeAuthModal() {
  $("#auth-modal").hidden = true;
  document.body.classList.remove("modal-open");
}

function showPublicView() {
  closeAuthModal();
  $("#site-header").hidden = true;
  $("#app-shell").hidden = true;
  $("#welcome-view").hidden = false;
}

function askForCode(email, message) {
  const form = $("#code-form");
  form.elements.email.value = email;
  $("#resend-email").value = email;
  showAuthForm("code");
  form.elements.code.focus();
  setMessage(form, message, true);
}

function showApp() {
  closeAuthModal();
  $("#welcome-view").hidden = true;
  $("#site-header").hidden = false;
  $("#app-shell").hidden = false;
  $("#admin-link").hidden = !state.user?.is_admin;
  $("#delete-card").hidden = Boolean(state.user?.is_admin);
}

async function loadProfile() {
  const data = await api("/api/profile");
  state.user = data.user;
  return state.user;
}

// Server logout ke saath browser ka token aur purana user data clear karna.
async function signOut(callApi = true) {
  if (callApi && state.token) {
    try {
      await api("/api/logout", { method: "POST" });
    } catch {
      // Server band ho tab bhi browser se logout karna.
    }
  }
  saveToken("");
  state.user = null;
  state.catalogue.clear();
  state.library.clear();
  state.adminBooks.clear();
  // Purane user ki library aur results screen se bhi hatane hain.
  $("#scan-result").innerHTML = "";
  $("#scan-result").hidden = true;
  $("#library-books").innerHTML = "";
  $("#library-count").textContent = "";
  $("#closest-books").innerHTML = "";
  $("#manual-form").reset();
  clearCoverInput();
  clearPhoto('barcode');
  closeCamera();
  history.replaceState(null, "", "/");
  showPublicView();
  showAuthForm("login", false);
}

function currentPage() {
  const name = window.location.hash.replace("#", "").split("/")[0] || "home";
  const allowed = ["home", "scan", "library", "profile", "admin"];
  return allowed.includes(name) ? name : "home";
}

// URL ke hash se page choose karna, jaise #scan ya #library.
async function route() {
  if (!state.token || !state.user) return;
  let page = currentPage();
  if (page === "admin" && !state.user.is_admin) page = "home";

  $$("[data-page]").forEach((section) => {
    section.hidden = section.dataset.page !== page;
  });
  $$("[data-page-link]").forEach((link) => {
    const active = link.dataset.pageLink === page;
    link.classList.toggle("active", active);
    if (active) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  });
  $("#main-nav").classList.remove("open");
  $("#menu-button").setAttribute("aria-expanded", "false");

  const loaders = {
    home: loadHome,
    library: loadLibrary,
    profile: loadProfilePage,
    admin: loadAdmin,
  };
  try {
    if (loaders[page]) await loaders[page]();
  } catch (error) {
    showToast(error.message);
  }

  const heading = $(`[data-page="${page}"] h1`);
  heading?.setAttribute("tabindex", "-1");
  heading?.focus({ preventScroll: true });
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function coverMarkup(book, className = "book-cover") {
  const cover = safeCover(book.cover_url);
  const title = escapeHtml(book.title || "book");
  if (!cover) return `<div class="${className} placeholder">No cover available</div>`;
  return `<img class="${className}" src="${escapeHtml(cover)}" alt="Cover of ${title}" loading="lazy"
    onerror="this.outerHTML='<div class=&quot;${className} placeholder&quot;>No cover available</div>'">`;
}

function bookCard(book, reason = "") {
  return `
    <article class="book-card">
      ${coverMarkup(book)}
      <div class="book-card-body">
        ${reason ? `<span class="book-reason">${escapeHtml(reason)}</span>` : ""}
        <div>
          <h3>${escapeHtml(book.title)}</h3>
          <p>${escapeHtml(book.author || "Unknown author")}</p>
        </div>
        <button class="button secondary small" type="button" data-book-id="${Number(book.id)}">View details</button>
      </div>
    </article>`;
}

function renderBookGrid(container, books, emptyMessage, reasonKey = "") {
  if (!books.length) {
    container.innerHTML = `<div class="empty-state">${escapeHtml(emptyMessage)}</div>`;
    return;
  }
  books.forEach((book) => state.catalogue.set(Number(book.id), book));
  container.innerHTML = books.map((book) => bookCard(book, book[reasonKey])).join("");
  $$('[data-book-id]', container).forEach((button) => {
    button.addEventListener("click", () => openCatalogueBook(Number(button.dataset.bookId)));
  });
}

// Home par reader ke counts aur suggestions load karne hain.
async function loadHome() {
  await loadProfile();
  $("#home-greeting").textContent = `Welcome back, ${state.user.name}`;
  $("#home-book-count").textContent = state.user.book_count;
  $("#home-interests").textContent = state.user.interests.length
    ? state.user.interests.join(", ")
    : "Not chosen yet";

  const data = await api("/api/closest");
  renderBookGrid(
    $("#closest-books"),
    data.books,
    "Save books or choose your interests to see suggestions.",
    "reason",
  );
}

function statusLabel(status) {
  const labels = {
    identified: "Identified",
    want_to_read: "Want to read",
    reading: "Reading",
    finished: "Finished",
  };
  return labels[status] || "Identified";
}

function statusOptions(selected) {
  return ["identified", "want_to_read", "reading", "finished"]
    .map((value) => `<option value="${value}" ${value === selected ? "selected" : ""}>${statusLabel(value)}</option>`)
    .join("");
}

const MIN_RATINGS = 10;
const EXACT_PAGE_SOURCES = ["open_library_isbn_edition", "google_isbn_volume", "isbn_verified_source"];

// Edition ki detail aur doosri editions ka estimate alag dikhana.
function bookFacts(book) {
  const facts = [];
  const pages = Number(book.page_count || 0);
  const rating = Number(book.rating || 0);
  const ratings = Number(book.ratings_count || 0);
  const shelves = Number(book.on_shelves || 0);
  const provider = book.source || "Book provider";

  // Votes kam hon to rating nahi dikhani; available ho to shelf count dikhana.
  if (rating > 0 && ratings >= MIN_RATINGS) {
    facts.push({
      label: "Reader rating",
      value: `${rating.toFixed(1)} / 5`,
      note: `${ratings.toLocaleString()} ratings · ${book.rating_source || provider}`,
    });
  } else if (shelves > 0) {
    facts.push({
      label: "On reader shelves",
      value: shelves.toLocaleString(),
      note: provider,
    });
  }
  if (pages > 0) {
    const exact = EXACT_PAGE_SOURCES.includes(book.page_count_source);
    facts.push({
      label: "Length",
      value: `About ${pages.toLocaleString()} pages`,
      note: exact ? `${provider} · listed edition` : `${provider} · varies by edition`,
    });
    if (exact) {
      facts.push({
        label: "Reading time",
        value: `About ${Math.max(1, Math.round(pages / 30))} hours`,
        note: "estimated at 30 pages an hour",
      });
    }
  }
  return facts;
}

function renderReaderSignals(book) {
  const facts = bookFacts(book);
  if (!facts.length) return "";
  return `<ul class="fact-list">${facts
    .map(
      (fact) => `<li>
      <span class="fact-label">${escapeHtml(fact.label)}</span>
      <strong class="fact-value">${escapeHtml(fact.value)}</strong>
      <span class="fact-note">${escapeHtml(fact.note)}</span>
    </li>`
    )
    .join("")}</ul>`;
}

// Edition details expand karke dekh sakte hain; missing value bhi clear dikhani hai.
function renderEditionSources(book) {
  const rows = [
    ["Publisher", book.publisher],
    ["Published", book.published_date],
    ["ISBN", book.isbn_13 || book.isbn_10],
  ];
  const provider = book.source || "Book provider";
  const reference = safeCover(book.catalogue_source_url);
  let sourceLinks = "";
  const ratingUrl = safeCover(book.rating_source_url);
  const overviewUrl = safeCover(book.overview_source_url);
  if (ratingUrl) {
    sourceLinks += `<p><a href="${escapeHtml(ratingUrl)}"
      target="_blank" rel="noopener noreferrer">View reader ratings</a></p>`;
  }
  if (overviewUrl) {
    sourceLinks += `<p><a href="${escapeHtml(overviewUrl)}"
      target="_blank" rel="noopener noreferrer">Overview source</a></p>`;
  }

  return `
    <details class="edition-sources">
      <summary>Book information</summary>
      <dl class="edition-list">
        ${rows
          .map(
            ([name, value]) => `<div>
          <dt>${escapeHtml(name)}</dt>
          <dd>${value ? escapeHtml(String(value)) : '<span class="not-listed">Not listed</span>'}</dd>
        </div>`
          )
          .join("")}
      </dl>
      ${sourceLinks}
      <p class="edition-note">${escapeHtml(book.catalogue_note || `Reader data and genres come from ${provider}. Page totals can differ between editions.`)}</p>
      ${reference ? `<a href="${escapeHtml(reference)}" target="_blank" rel="noopener noreferrer">View catalogue reference</a>` : ""}
    </details>`;
}

// Lambi description pehle chhoti dikhani hai, phir expand kar sakte hain.
function renderOverview(text) {
  const full = String(text || "");
  if (full.length <= 420) return `<p>${escapeHtml(full)}</p>`;
  return `
    <p class="overview-short">${escapeHtml(full.slice(0, 420))}…</p>
    <p class="overview-full" hidden>${escapeHtml(full)}</p>
    <button class="button quiet" type="button" data-overview-toggle>Read more</button>`;
}

// Description na ho to apni taraf se overview nahi banana.
function renderOverviewSection(book, heading) {
  const text = book.overview || "";
  if (!text) return "";
  return `<${heading}>Overview</${heading}>${renderOverview(text)}`;
}

function bindOverviewToggle(container) {
  const button = $("[data-overview-toggle]", container);
  if (!button) return;
  button.addEventListener("click", () => {
    const short = $(".overview-short", container);
    const full = $(".overview-full", container);
    const expanded = !full.hidden;
    short.hidden = !expanded;
    full.hidden = expanded;
    button.textContent = expanded ? "Read more" : "Show less";
  });
}

// Provider ke bohat saare subjects hon to pehle kuch genres dikhane hain.
function renderGenres(book) {
  const genres = (book.genres || []).slice(0, 4);
  if (!genres.length) return "";
  return `<ul class="genre-list">${genres
    .map((genre) => `<li>${escapeHtml(genre)}</li>`)
    .join("")}</ul>`;
}

function renderSource(book) {
  if (!book.source) return "";
  return `<span class="source-note">${escapeHtml(book.source)}</span>`;
}

function renderCandidateReasons(book) {
  // Matching ki reason backend se aa chuki hai, yahan dikhani hai.
  const reasons = book.reasons || [];
  if (!reasons.length) return "";
  const items = reasons.map((reason) => {
    const warn = /does not match|weak|similar scores/i.test(reason) ? ' class="warn"' : "";
    return `<li${warn}>${escapeHtml(reason)}</li>`;
  });
  return `<ul class="reason-list">${items.join("")}</ul>`;
}

function renderCandidate(book) {
  const authors = String(book.author || "Unknown author").split(/[,;]/).map(x => x.trim()).filter(Boolean);
  const primaryAuthor = authors[0];
  const conflict = (book.reasons || []).some(reason => /author does not match/i.test(reason));
  const source = book.provider === "catalogue" ? "Bookrift catalogue" : "Online book result";
  return `
    <article class="candidate candidate-rich">
      ${coverMarkup(book, "candidate-cover")}
      <div class="candidate-copy">
        <span class="source-note">${escapeHtml(source)}</span>
        <h3>${escapeHtml(book.title)}</h3>
        <p>By ${escapeHtml(primaryAuthor)}${authors.length > 1 ? ` · +${authors.length - 1} contributors` : ""}</p>
        <p class="match-status${conflict ? " warn" : ""}">${conflict ? "Check the author before choosing." : "Select the title and edition that matches your book."}</p>
        <details class="edition-sources">
          <summary>Book details</summary>
          ${renderCandidateReasons(book)}
          <dl class="edition-list">
            <div><dt>Authors / contributors</dt><dd>${escapeHtml(book.author || "Not listed")}</dd></div>
            <div><dt>Publisher</dt><dd>${escapeHtml(book.publisher || "Not listed")}</dd></div>
            <div><dt>Published</dt><dd>${escapeHtml(book.published_date || "Not listed")}</dd></div>
            <div><dt>ISBN</dt><dd>${escapeHtml(book.isbn_13 || book.isbn_10 || "Not listed")}</dd></div>
          </dl>
          <p class="edition-note">View the author, publisher, date, and ISBN for this edition.</p>
        </details>
      </div>
      <button class="button secondary" type="button" data-confirm="${Number(book.candidate_id)}">Choose this book</button>
    </article>`;
}

const TASTE_HEADINGS = {
  good_match: "Why you may like it",
  interest_match: "Matches your interests",
  different_from_your_books: "Try something new",
  different_from_your_interests: "Explore a new genre",
  cold_start: "Personalise your suggestions",
  no_genres: "More about this book",
};

function renderTasteState(fit, book) {
  if (!fit) return "";
  const genres = (fit.shared_genres || []).join(" and ");
  const because = (fit.because || []).join(" and ");
  const own = ((book && book.genres) || []).join(", ");
  let body = "";

  if (fit.status === "good_match") {
    body = `You read ${because}. This one shares ${genres}.`;
  } else if (fit.status === "interest_match") {
    body = `Matches your interest in ${genres}.`;
  } else if (fit.status === "different_from_your_books") {
    body = own
      ? `This is different from the books you usually read. It is ${own}.`
      : "This is different from the books you usually read.";
  } else if (fit.status === "different_from_your_interests") {
    body = own
      ? `This is outside the interests you chose. It is ${own}.`
      : "This is outside the interests you chose.";
  } else if (fit.status === "cold_start") {
    body = "Add favourites, reading history, or interests to get personal suggestions.";
  } else {
    body = "Open the book to explore its available details.";
  }

  const quiet = fit.status === "good_match" || fit.status === "interest_match" ? "" : " quiet";
  return `<div class="reader-fit${quiet}"><strong>${escapeHtml(TASTE_HEADINGS[fit.status] || "")}</strong><span>${escapeHtml(body)}</span></div>`;
}

function libraryItem(item) {
  const book = item.book;
  return `
    <article class="library-item">
      ${coverMarkup(book)}
      <div class="library-info">
        <span class="status-badge">${escapeHtml(statusLabel(item.reading_status))}</span>
        <h3>${escapeHtml(book.title)}</h3>
        <p>${escapeHtml(book.author || "Unknown author")}</p>
        <button class="text-action" type="button" data-library-detail="${item.library_id}">View details</button>
      </div>
      <div class="library-actions">
        <select aria-label="Reading status for ${escapeHtml(book.title)}" data-library-status="${item.library_id}">
          ${statusOptions(item.reading_status)}
        </select>
        <button class="button secondary small" type="button" data-favorite="${item.library_id}">${item.favorite ? "Remove favorite" : "Add favorite"}</button>
        <button class="button small danger" type="button" data-remove="${item.library_id}">Remove</button>
      </div>
    </article>`;
}

async function loadLibrary() {
  const form = $("#library-filters");
  const params = new URLSearchParams();
  const data = new FormData(form);
  for (const [key, value] of data.entries()) {
    if (String(value).trim()) params.set(key, String(value).trim());
  }
  const result = await api(`/api/history?${params}`);
  $("#library-count").textContent = `${result.total} saved book${result.total === 1 ? "" : "s"}`;
  state.library.clear();
  result.items.forEach((item) => state.library.set(Number(item.library_id), item));
  const container = $("#library-books");
  container.innerHTML = result.items.length
    ? result.items.map(libraryItem).join("")
    : '<div class="empty-state">Your library is empty. Scan a book cover to add your first book.</div>';
  bindLibraryActions();
}

// Library ke favourite, status aur remove buttons ki requests.
function bindLibraryActions() {
  $$('[data-library-detail]').forEach((button) => {
    button.addEventListener("click", async () => {
      const item = state.library.get(Number(button.dataset.libraryDetail));
      if (!item) return;
      // Details kholte waqt book ka full record mangwana.
      try {
        const full = await api(`/api/books/${item.book.id}`);
        openBookDialog(full.book, full);
      } catch (error) {
        showToast(error.message);
      }
    });
  });
  $$('[data-library-status]').forEach((select) => {
    select.addEventListener("change", async () => {
      try {
        await api(`/api/history/${select.dataset.libraryStatus}/reading`, {
          method: "PATCH",
          body: JSON.stringify({ reading_status: select.value }),
        });
        showToast("Reading status updated.");
        await loadLibrary();
      } catch (error) {
        showToast(error.message);
      }
    });
  });
  $$('[data-favorite]').forEach((button) => {
    button.addEventListener("click", async () => {
      try {
        await api(`/api/history/${button.dataset.favorite}/favorite`, { method: "POST" });
        showToast("Favorite updated.");
        await loadLibrary();
      } catch (error) {
        showToast(error.message);
      }
    });
  });
  $$('[data-remove]').forEach((button) => {
    button.addEventListener("click", async () => {
      if (!await askConfirm("Remove this book from your library?")) return;
      try {
        await api(`/api/history/${button.dataset.remove}`, { method: "DELETE" });
        showToast("Book removed from your library.");
        await loadLibrary();
      } catch (error) {
        showToast(error.message);
      }
    });
  });
}

async function openCatalogueBook(bookId) {
  try {
    const data = await api(`/api/catalogue/${bookId}`);
    openBookDialog(data.book, data);
  } catch (error) {
    showToast(error.message);
  }
}

function openBookDialog(book, library = {}) {
  const saved = Boolean(library.library_id);
  $("#book-detail").innerHTML = `
    <div class="book-detail-layout">
      <div class="result-cover">
        ${coverMarkup(book)}
        ${renderSource(book)}
      </div>
      <div>
        <h1>${escapeHtml(book.title)}</h1>
        <p class="lead">${escapeHtml(book.author || "Unknown author")}</p>
        ${renderGenres(book)}
        ${renderReaderSignals(book)}
        ${renderTasteState(library.for_you, book)}
        ${renderOverviewSection(book, "h2")}
        ${renderEditionSources(book)}
        <div class="detail-actions">
          ${saved ? `<span class="status-badge">${escapeHtml(statusLabel(library.reading_status))}</span>` : `
            <select id="detail-reading-status" aria-label="Choose reading status">
              <option value="want_to_read">Want to read</option>
              <option value="reading">Reading</option>
              <option value="finished">Finished</option>
            </select>
            <button class="button primary" type="button" id="save-catalogue-book">Add to library</button>`}
        </div>
      </div>
    </div>`;

  bindOverviewToggle($("#book-detail"));

  if (!saved) {
    $("#save-catalogue-book")?.addEventListener("click", async () => {
      const button = $("#save-catalogue-book");
      button.disabled = true;
      try {
        await api(`/api/catalogue/${book.id}/read`, {
          method: "POST",
          body: JSON.stringify({ reading_status: $("#detail-reading-status").value }),
        });
        showToast("Book added to your library.");
        $("#book-dialog").close();
      } catch (error) {
        button.disabled = false;
        showToast(error.message);
      }
    });
  }
  $("#book-dialog").showModal();
}

function showScanLoading(message) {
  const result = $("#scan-result");
  result.hidden = false;
  result.innerHTML = `<div class="loading-state"><span class="spinner" aria-hidden="true"></span><span>${escapeHtml(message)}</span></div>`;
}

// Form bhejna aur loading, result ya error dikhana.
async function runIdentification(form, path, body, json = false) {
  // Manual search aur photo scan ka loading text alag rakhna.
  const messages = [
    json ? "Searching for the book..." : "Reading the image...",
    "Checking the title and author...",
    "Comparing possible books...",
    "Finishing the result...",
  ];
  let step = 0;
  showScanLoading(messages[step]);
  setBusy(form, true, "Working...");
  setPhotoBusy(form, true);
  const timer = setInterval(() => {
    step = Math.min(step + 1, messages.length - 1);
    showScanLoading(messages[step]);
  }, 2400);

  try {
    const options = { method: "POST", body: json ? JSON.stringify(body) : body };
    const data = await api(path, options);
    renderIdentification(data);
  } catch (error) {
    const heading = error.status === 429 ? "Just a moment" : "Could not finish.";
    $("#scan-result").innerHTML = `<div class="empty-state"><strong>${heading}</strong><br>${escapeHtml(error.message)}</div>`;
  } finally {
    clearInterval(timer);
    setBusy(form, false);
    setPhotoBusy(form, false);
  }
}

// Server ke decision ke hisaab se result ya candidate choices dikhani hain.
function renderIdentification(data) {
  const result = $("#scan-result");
  result.hidden = false;
  if (data.status === "needs_confirmation") {
    result.innerHTML = `
      <p class="eyebrow">Select your book</p>
      <h2>Choose the matching book</h2>
      <p>${escapeHtml(data.message)}</p>
      <div class="candidate-list">
        ${data.candidates.slice(0, 3).map(renderCandidate).join("")}
        ${data.candidates.length > 3 ? `<details class="more-candidates"><summary>Show ${data.candidates.length - 3} other possible books</summary>${data.candidates.slice(3).map(renderCandidate).join("")}</details>` : ""}
      </div>
      <button class="button quiet candidate-reset" type="button" id="decline-candidates">None of these is my book</button>`;
    $$('[data-confirm]', result).forEach((button) => {
      button.addEventListener("click", () => confirmCandidate(data.attempt_id, Number(button.dataset.confirm), button));
    });
    $("#decline-candidates").addEventListener("click", async () => {
      const button = $("#decline-candidates");
      button.disabled = true;
      button.textContent = "Updating...";
      try {
        const rejected = await api("/api/identify/reject", {
          method: "POST",
          body: JSON.stringify({ attempt_id: data.attempt_id }),
        });
        renderRejection({ ...data, ...rejected });
      } catch (error) {
        button.disabled = false;
        button.textContent = "None of these is my book";
        showToast(error.message);
      }
    });
    return;
  }

  if (data.status === "success") {
    result.innerHTML = renderResultCard(data);
    bindResultActions(data);
    bindOverviewToggle(result);
    return;
  }

  renderRejection(data);
}

function clearCoverInput() {
  clearPhoto('cover');
}

function bindResultActions(data) {
  $("#scan-again").addEventListener("click", () => {
    clearCoverInput();
    moveToScanForm("#cover-form", "#cover-image");
  });
  $("#search-another").addEventListener("click", () => {
    $("#manual-form").reset();
    moveToScanForm("#manual-form", "#manual-title");
  });

  const wrongBook = $("#wrong-book");
  if (!wrongBook) return;
  wrongBook.addEventListener("click", async () => {
    if (!await askConfirm("Remove this book and search again?")) return;
    wrongBook.disabled = true;
    try {
      await api(`/api/history/${data.library_id}`, { method: "DELETE" });
      showToast("Removed. Try searching for the right book.");
      $("#manual-form").reset();
      $("#manual-title").value = data.book.title;
      moveToScanForm("#manual-form", "#manual-title");
    } catch (error) {
      wrongBook.disabled = false;
      showToast(error.message);
    }
  });
}

function renderResultCard(data) {
  const book = data.book;
  // Undo sirf is scan ki nayi save par; purani library entry nahi hatani.
  const justSaved = !data.already_in_library && Boolean(data.library_id);
  const savedText = data.already_in_library
    ? `Already in your library · ${statusLabel(data.reading_status)}${data.favorite ? " · Favorite" : ""}`
    : "Saved to your library";
  return `
    <div class="success-result">
      <div class="result-cover">
        ${coverMarkup(book)}
        ${renderSource(book)}
      </div>
      <div>
        <span class="status-badge">${escapeHtml(savedText)}</span>
        <h2>${escapeHtml(book.title)}</h2>
        <p class="lead">${escapeHtml(book.author || "Unknown author")}</p>
        ${renderGenres(book)}
        ${renderReaderSignals(book)}
        ${renderTasteState(data.for_you, book)}
        ${renderOverviewSection(book, "h3")}
        ${renderEditionSources(book)}
      </div>
    </div>
    <div class="detail-actions">
      <button class="button secondary" type="button" id="scan-again">Scan another cover</button>
      <button class="button secondary" type="button" id="search-another">Search another book</button>
      ${justSaved ? '<button class="button quiet" type="button" id="wrong-book">Not the right book?</button>' : ""}
    </div>`;
}

function scanRecoveryCopy(data) {
  const method = data.input_method || "cover";
  const ocrStatus = data.ocr?.status || "";
  if (method === "barcode") {
    return {
      title: "Barcode not recognised.",
      hint: "Keep the full barcode flat, clear, and inside the photo.",
    };
  }
  if (method === "manual") {
    return {
      title: "No reliable title match found.",
      hint: "Try a shorter title, add the author, or enter the ISBN.",
    };
  }
  if (ocrStatus === "OCR_NO_BOOK_TEXT") {
    return {
      title: "This does not look like a readable book cover.",
      hint: "Use the front cover in good light and keep other text out of the frame.",
    };
  }
  if (["OCR_FAILED", "OCR_LOW_CONFIDENCE"].includes(ocrStatus)) {
    return {
      title: "The cover text was not clear enough.",
      hint: "Move closer, avoid glare, and keep the title and author visible.",
    };
  }
  return {
    title: "No reliable match found.",
    hint: "Try a clearer cover, scan the barcode, or search by title.",
  };
}

function moveToScanForm(formSelector, inputSelector) {
  $(formSelector).scrollIntoView({ behavior: "smooth", block: "center" });
  $(inputSelector).focus();
}

function renderRejection(data) {
  const result = $("#scan-result");
  const copy = scanRecoveryCopy(data);
  const detail = data.failure_reason || data.message || "";
  result.innerHTML = `
    <div class="refusal">
      <p class="eyebrow">Not identified</p>
      <h2>${escapeHtml(copy.title)}</h2>
      ${detail ? `<p>${escapeHtml(detail)}</p>` : ""}
      <p class="recovery-note">${escapeHtml(copy.hint)}</p>
      <div class="recovery-actions">
        <button class="button primary" type="button" id="retry-cover">Scan front cover</button>
        <button class="button secondary" type="button" id="retry-barcode">Scan barcode</button>
        <button class="button secondary" type="button" id="try-manual">Use manual search</button>
      </div>
      <div id="closest-recovery-books"></div>
    </div>`;

  $("#retry-cover").addEventListener("click", () => moveToScanForm("#cover-form", "#cover-image"));
  $("#retry-barcode").addEventListener("click", () => moveToScanForm("#barcode-form", "#barcode-image"));
  $("#try-manual").addEventListener("click", () => {
    const title = String(data.recovery_query || "").trim();
    if (title) $("#manual-title").value = title;
    moveToScanForm("#manual-form", "#manual-title");
  });

  loadClosestRecoveryBooks().catch(() => {});
}

async function loadClosestRecoveryBooks() {
  const target = $("#closest-recovery-books");
  if (!target) return;
  const data = await api("/api/closest");
  if (!data.books.length) return;

  data.books.forEach((book) => state.catalogue.set(Number(book.id), book));
  target.innerHTML = `
    <div class="recovery-heading">
      <strong>Other books you may like</strong>
      <span>Based on your saved books and interests.</span>
    </div>
    <div class="candidate-list">
      ${data.books.map((book) => `
        <article class="candidate candidate-rich">
          ${coverMarkup(book, "candidate-cover")}
          <div class="candidate-copy">
            <h3>${escapeHtml(book.title)}</h3>
            <p>${escapeHtml(book.author || "Unknown author")}</p>
            <p class="candidate-meta">${escapeHtml(book.reason || "")}</p>
          </div>
          <button class="button secondary" type="button" data-closest-book="${Number(book.id)}">View details</button>
        </article>`).join("")}
    </div>`;
  $$('[data-closest-book]', target).forEach((button) => {
    button.addEventListener("click", () => openCatalogueBook(Number(button.dataset.closestBook)));
  });
}

// Selected candidate ki ID bhejni hai, book details khud se confirm nahi karni.
async function confirmCandidate(attemptId, candidateId, button) {
  button.disabled = true;
  button.textContent = "Saving...";
  try {
    const data = await api("/api/identify/confirm", {
      method: "POST",
      body: JSON.stringify({ attempt_id: attemptId, candidate_id: candidateId }),
    });
    renderIdentification(data);
  } catch (error) {
    button.disabled = false;
    button.textContent = "Choose this book";
    showToast(error.message);
  }
}

async function loadProfilePage() {
  await loadProfile();
  $("#profile-details").innerHTML = `
    <dt>Name</dt><dd>${escapeHtml(state.user.name)}</dd>
    <dt>Email</dt><dd>${escapeHtml(state.user.email)}</dd>
    <dt>Books</dt><dd>${Number(state.user.book_count)}</dd>
    <dt>Role</dt><dd>${state.user.is_admin ? "Administrator" : "Reader"}</dd>`;

  const data = await api("/api/interests");
  const selected = new Set(data.selected);
  $("#interest-list").innerHTML = data.available.map((interest) => `
    <label class="interest-option">
      <input type="checkbox" name="interests" value="${escapeHtml(interest)}" ${selected.has(interest) ? "checked" : ""}>
      <span>${escapeHtml(interest)}</span>
    </label>`).join("");
}

async function loadAdminStats() {
  const data = await api("/api/admin/stats");
  const totals = [
    ["Users", data.total_users],
    ["Books", data.total_books],
    ["Library items", data.total_library_items],
    ["Scans", data.total_attempts],
    ["Messages", data.total_messages],
  ];
  $("#admin-stats").innerHTML = totals.map(([label, value]) => `
    <article class="summary-card"><span>${escapeHtml(label)}</span><strong>${Number(value || 0)}</strong></article>`).join("");
  $("#recent-scans").innerHTML = data.recent_scans.length
    ? data.recent_scans.map((scan) => `<tr><td>${escapeHtml(scan.title || "No match")}</td><td>${escapeHtml(scan.user_name)}</td><td>${escapeHtml(scan.decision)}</td></tr>`).join("")
    : '<tr><td colspan="3">No scans yet.</td></tr>';
  $("#recent-messages").innerHTML = data.recent_messages.length
    ? data.recent_messages.map((message) => `<article class="message-item"><strong>${escapeHtml(message.subject || "General message")}</strong><p>${escapeHtml(message.name)} · ${escapeHtml(message.email)}</p><small>${escapeHtml(message.message)}</small></article>`).join("")
    : '<p class="empty-state">No messages yet.</p>';
}

function adminStatusLabel(status) {
  const labels = {
    VERIFIED: "Verified",
    PENDING: "Pending",
    NEEDS_REVIEW: "Needs review",
    REJECTED: "Rejected",
  };
  return labels[status] || "Pending";
}

function adminStatusClass(status) {
  return String(status || "PENDING").toLowerCase().replaceAll("_", "-");
}

function adminBookRow(book) {
  const status = book.catalogue_status || "PENDING";
  const isbn = book.isbn_13 || book.isbn_10 || "No ISBN";
  const reference = safeCover(book.catalogue_source_url);
  return `
    <article class="admin-book-row">
      ${coverMarkup(book)}
      <div class="admin-book-main">
        <h3>${escapeHtml(book.title)}</h3>
        <p>${escapeHtml(book.author || "Unknown author")}</p>
        ${reference ? `<a href="${escapeHtml(reference)}" target="_blank" rel="noopener noreferrer">Title / author reference</a>` : ""}
      </div>
      <div class="admin-book-meta">
        <span class="record-status ${adminStatusClass(status)}">${escapeHtml(adminStatusLabel(status))}</span>
        <span>${escapeHtml(isbn)}</span>
      </div>
      <div class="admin-book-actions">
        <button class="button danger small" type="button" data-admin-delete="${Number(book.id)}">Delete</button>
        <button class="button secondary small" type="button" data-admin-edit="${Number(book.id)}">Edit</button>
        ${status === "VERIFIED" ? "" : `<button class="button secondary small" type="button" data-admin-status="${Number(book.id)}" data-status="VERIFIED">Verify</button>`}
        ${status === "NEEDS_REVIEW" ? "" : `<button class="button secondary small" type="button" data-admin-status="${Number(book.id)}" data-status="NEEDS_REVIEW">Review</button>`}
        ${status === "REJECTED" ? "" : `<button class="button danger small" type="button" data-admin-status="${Number(book.id)}" data-status="REJECTED">Reject</button>`}
      </div>
    </article>`;
}

async function loadAdminCatalogue() {
  const form = $("#admin-catalogue-filter");
  const params = new URLSearchParams();
  for (const [key, value] of new FormData(form).entries()) {
    if (String(value).trim()) params.set(key, String(value).trim());
  }
  $("#admin-book-list").innerHTML = '<div class="empty-state">Loading catalogue records...</div>';
  const data = await api(`/api/admin/catalogue?${params}`);
  state.adminBooks.clear();
  data.books.forEach((book) => state.adminBooks.set(Number(book.id), book));
  $("#admin-catalogue-count").textContent = `${data.total} record${data.total === 1 ? "" : "s"}`;
  $("#admin-book-list").innerHTML = data.books.length
    ? data.books.map(adminBookRow).join("")
    : '<div class="empty-state">No catalogue records match these filters.</div>';
  bindAdminBookActions();
}

function bindAdminBookActions() {
  $$('[data-admin-delete]').forEach(button => {
    button.addEventListener('click', async () => {
      const book = state.adminBooks.get(Number(button.dataset.adminDelete));
      if (!book || !await askConfirm(`Permanently delete “${book.title}”? This cannot be undone. Books saved by readers are protected.`)) return;
      button.disabled = true;
      try {
        const result = await api(`/api/admin/catalogue/${book.id}`, {method: 'DELETE'});
        showToast(result.message);
        await Promise.all([loadAdminCatalogue(), loadAdminStats()]);
      } catch (error) {
        button.disabled = false;
        showToast(error.message);
      }
    });
  });
  $$('[data-admin-edit]').forEach((button) => {
    button.addEventListener("click", () => {
      const book = state.adminBooks.get(Number(button.dataset.adminEdit));
      if (book) openAdminBookForm(book);
    });
  });
  $$('[data-admin-status]').forEach((button) => {
    button.addEventListener("click", () => updateAdminStatus(
      Number(button.dataset.adminStatus),
      button.dataset.status,
      button,
    ));
  });
}

async function updateAdminStatus(bookId, status, button) {
  if (status === "REJECTED" && !await askConfirm("Mark this catalogue record as rejected?")) return;
  button.disabled = true;
  try {
    await api(`/api/admin/catalogue/${bookId}`, {
      method: "PATCH",
      body: JSON.stringify({ catalogue_status: status }),
    });
    showToast(`Record marked as ${adminStatusLabel(status).toLowerCase()}.`);
    await Promise.all([loadAdminCatalogue(), loadAdminStats()]);
  } catch (error) {
    button.disabled = false;
    showToast(error.message);
  }
}

function displayDate(value) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "—" : date.toLocaleDateString();
}

async function loadIdentificationReview() {
  const data = await api("/api/admin/identifications?limit=50");
  $("#identification-rows").innerHTML = data.attempts.length
    ? data.attempts.map((attempt) => `
      <tr>
        <td>${escapeHtml(attempt.selected_title || attempt.query_title || attempt.ocr_title || "No title")}</td>
        <td>${escapeHtml(attempt.input_method)}</td>
        <td>${escapeHtml(attempt.ocr_status || "—")}</td>
        <td>${escapeHtml(attempt.decision)}</td>
        <td>${escapeHtml(displayDate(attempt.created_at))}</td>
      </tr>`).join("")
    : '<tr><td colspan="5">No identification attempts yet.</td></tr>';
}

async function loadAdminSystem() {
  const data = await api("/api/admin/system");
  $("#admin-system-line").textContent = `Database ${data.database} · ${data.ocr} · ${data.barcode}`;
}

// Selected admin tab ka data load karna.
async function loadAdmin() {
  if (!state.user?.is_admin) return;
  const panels = ['overview', 'catalogue', 'scans', 'messages', 'system'];
  const requested = window.location.hash.split('/')[1] || 'overview';
  const active = panels.includes(requested) ? requested : 'overview';
  $$('[data-admin-panel]').forEach(panel => { panel.hidden = panel.dataset.adminPanel !== active; });
  $$('[data-admin-tab]').forEach(link => {
    const selected = link.dataset.adminTab === active;
    link.classList.toggle('active', selected);
    if (selected) link.setAttribute('aria-current', 'page');
    else link.removeAttribute('aria-current');
  });
  const loaders = {
    overview: loadAdminStats, catalogue: loadAdminCatalogue,
    scans: () => Promise.all([loadIdentificationReview(), loadAdminStats()]),
    messages: loadAdminStats, system: loadAdminSystem,
  };
  await loaders[active]();
}

const ADMIN_FIELDS = [
  "title", "author", "catalogue_status", "isbn_10", "isbn_13", "publisher",
  "published_date", "genres", "cover_url", "description", "overview",
  "google_books_id", "open_library_edition_id", "open_library_work_id",
];

function openAdminBookForm(book = null) {
  const form = $("#admin-book-form");
  form.reset();
  setMessage(form);
  form.elements.book_id.value = book?.id || "";
  $("#admin-form-title").textContent = book ? "Edit book" : "Add book";
  ADMIN_FIELDS.forEach((field) => {
    const input = form.elements[field];
    if (!input || !book) return;
    const value = field === "genres" && Array.isArray(book[field])
      ? book[field].join(", ")
      : book[field];
    input.value = value ?? "";
  });
  state.adminFormDirty = false;
  $("#admin-book-dialog").showModal();
  form.elements.title.focus();
}

async function closeAdminBookForm(force = false) {
  if (!force && state.adminFormDirty && !await askConfirm("Close without saving your changes?")) return;
  state.adminFormDirty = false;
  $("#admin-book-dialog").close();
}

// Forms submit hon to unki API request chalani hai.
function bindForms() {
  $("#login-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const values = Object.fromEntries(new FormData(form));
    setMessage(form);
    setBusy(form, true, "Signing in...");
    try {
      const data = await api("/api/login", { method: "POST", body: JSON.stringify(values) });
      saveToken(data.token);
      state.user = data.user;
      showApp();
      window.location.hash = "home";
      await route();
    } catch (error) {
      if (error.status === 403) {
        askForCode(values.email, "Please verify your email first. Enter the code we sent you.");
      } else {
        setMessage(form, error.message);
      }
    } finally {
      setBusy(form, false);
    }
  });

  $("#register-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const values = Object.fromEntries(new FormData(form));
    setMessage(form);
    setBusy(form, true, "Creating account...");
    try {
      const data = await api("/api/register", { method: "POST", body: JSON.stringify(values) });
      form.reset();
      askForCode(values.email, data.message);
    } catch (error) {
      setMessage(form, error.message);
    } finally {
      setBusy(form, false);
    }
  });

  $("#forgot-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    setMessage(form);
    setBusy(form, true, "Sending...");
    try {
      const values = Object.fromEntries(new FormData(form));
      const data = await api("/api/forgot-password", { method: "POST", body: JSON.stringify(values) });
      const resetForm = $("#reset-form");
      resetForm.elements.email.value = values.email;
      showAuthForm("reset");
      setMessage(resetForm, data.message, true);
    } catch (error) {
      setMessage(form, error.message);
    } finally {
      setBusy(form, false);
    }
  });

  $("#resend-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    setMessage(form);
    setBusy(form, true, "Sending...");
    try {
      const values = Object.fromEntries(new FormData(form));
      const data = await api("/api/resend-verification", { method: "POST", body: JSON.stringify(values) });
      askForCode(values.email, data.message);
    } catch (error) {
      setMessage(form, error.message);
    } finally {
      setBusy(form, false);
    }
  });

  $("#code-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    setMessage(form);
    setBusy(form, true, "Checking...");
    try {
      const values = Object.fromEntries(new FormData(form));
      const data = await api("/api/verify-email", { method: "POST", body: JSON.stringify(values) });
      form.reset();
      showAuthForm("login");
      $("#login-form").elements.email.value = values.email;
      setMessage($("#login-form"), data.message, true);
    } catch (error) {
      setMessage(form, error.message);
    } finally {
      setBusy(form, false);
    }
  });

  $("#reset-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    setMessage(form);
    setBusy(form, true, "Updating...");
    try {
      const values = Object.fromEntries(new FormData(form));
      const data = await api("/api/reset-password", { method: "POST", body: JSON.stringify(values) });
      form.reset();
      showAuthForm("login");
      $("#login-form").elements.email.value = values.email;
      setMessage($("#login-form"), data.message, true);
    } catch (error) {
      setMessage(form, error.message);
    } finally {
      setBusy(form, false);
    }
  });

  $("#contact-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    setMessage(form);
    setBusy(form, true, "Sending...");
    try {
      const values = Object.fromEntries(new FormData(form));
      const data = await api("/api/contact", { method: "POST", body: JSON.stringify(values) });
      form.reset();
      setMessage(form, data.message, true);
    } catch (error) {
      setMessage(form, error.message);
    } finally {
      setBusy(form, false);
    }
  });

  $("#cover-form").addEventListener("submit", (event) => {
    event.preventDefault();
    runIdentification(event.currentTarget, "/api/scan", new FormData(event.currentTarget));
  });
  $("#barcode-form").addEventListener("submit", (event) => {
    event.preventDefault();
    runIdentification(event.currentTarget, "/api/barcode", new FormData(event.currentTarget));
  });
  $("#manual-form").addEventListener("submit", (event) => {
    event.preventDefault();
    const values = Object.fromEntries(new FormData(event.currentTarget));
    runIdentification(event.currentTarget, "/api/search-by-title", values, true);
  });

  $("#library-filters").addEventListener("submit", (event) => {
    event.preventDefault();
    loadLibrary().catch((error) => showToast(error.message));
  });
  $("#admin-catalogue-filter").addEventListener("submit", (event) => {
    event.preventDefault();
    loadAdminCatalogue().catch((error) => showToast(error.message));
  });

  $("#admin-book-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const bookId = form.elements.book_id.value;
    const values = {};
    ADMIN_FIELDS.forEach((field) => {
      values[field] = String(form.elements[field].value || "").trim();
    });
    setMessage(form);
    setBusy(form, true, "Saving...");
    try {
      const path = bookId ? `/api/admin/catalogue/${bookId}` : "/api/admin/catalogue";
      const data = await api(path, {
        method: bookId ? "PATCH" : "POST",
        body: JSON.stringify(values),
      });
      state.adminFormDirty = false;
      closeAdminBookForm(true);
      showToast(data.message);
      await Promise.all([loadAdminCatalogue(), loadAdminStats()]);
    } catch (error) {
      setMessage(form, error.message);
    } finally {
      setBusy(form, false);
    }
  });

  $("#interests-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const interests = new FormData(form).getAll("interests");
    if (interests.length > 5) {
      setMessage(form, "Choose no more than five interests.");
      return;
    }
    setBusy(form, true, "Saving...");
    try {
      await api("/api/profile/interests", { method: "POST", body: JSON.stringify({ interests }) });
      setMessage(form, "Interests saved.", true);
      await loadProfile();
    } catch (error) {
      setMessage(form, error.message);
    } finally {
      setBusy(form, false);
    }
  });

  $("#send-password-code").addEventListener("click", async (event) => {
    const form = $("#password-form");
    if (!form.elements.current_password.reportValidity()) return;
    const button = event.currentTarget;
    button.disabled = true;
    setMessage(form);
    setBusy(form, true, "Sending...");
    try {
      const data = await api("/api/profile/password/code", {
        method: "POST",
        body: JSON.stringify({ current_password: form.elements.current_password.value }),
      });
      form.elements.code.value = "";
      setMessage(form, data.message, true);
      form.elements.code.focus();
    } catch (error) {
      setMessage(form, error.message);
    } finally {
      button.disabled = false;
      setBusy(form, false);
    }
  });

  $("#password-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    setBusy(form, true, "Changing...");
    try {
      const data = await api("/api/profile/password", { method: "POST", body: JSON.stringify(Object.fromEntries(new FormData(form))) });
      showToast(data.message);
      await signOut(false);
    } catch (error) {
      setMessage(form, error.message);
    } finally {
      setBusy(form, false);
    }
  });
}

function bindControls() {
  $$('[data-auth-view]').forEach((button) => {
    button.addEventListener("click", () => showAuthForm(button.dataset.authView));
  });
  $("#show-forgot").addEventListener("click", () => showAuthForm("forgot"));
  $("#auth-close").addEventListener("click", closeAuthModal);
  $("#auth-modal").addEventListener("click", (event) => {
    if (event.target === $("#auth-modal")) closeAuthModal();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !$("#auth-modal").hidden) closeAuthModal();
  });
  $("#logout-button").addEventListener("click", () => signOut());
  $("#menu-button").addEventListener("click", () => {
    const menu = $("#main-nav");
    const open = menu.classList.toggle("open");
    $("#menu-button").setAttribute("aria-expanded", String(open));
  });
  $("#dialog-close").addEventListener("click", () => $("#book-dialog").close());
  $("#book-dialog").addEventListener("click", (event) => {
    if (event.target === $("#book-dialog")) $("#book-dialog").close();
  });
  $("#new-admin-book").addEventListener("click", () => openAdminBookForm());
  $("#admin-dialog-close").addEventListener("click", () => closeAdminBookForm());
  $("#admin-form-cancel").addEventListener("click", () => closeAdminBookForm());
  $("#admin-book-form").addEventListener("input", () => {
    state.adminFormDirty = true;
  });
  $("#admin-book-dialog").addEventListener("cancel", (event) => {
    event.preventDefault();
    closeAdminBookForm();
  });

  $("#interest-list").addEventListener("change", (event) => {
    const checked = $$('#interest-list input:checked');
    if (checked.length > 5) {
      event.target.checked = false;
      setMessage($("#interests-form"), "You can choose up to five interests.");
    } else {
      setMessage($("#interests-form"));
    }
  });

  $("#delete-account").addEventListener("click", async () => {
    if (!await askConfirm("Delete your account and all saved library data?")) return;
    const password = await askPassword("Enter your password to confirm deleting your account.");
    if (!password) return;
    try {
      const data = await api("/api/profile", { method: "DELETE", body: JSON.stringify({ password }) });
      showToast(data.message);
      await signOut(false);
    } catch (error) {
      showToast(error.message);
    }
  });
}

// Page khulte hi controls ready karna aur saved login check karna.
async function start() {
  setupPhotos();
  bindForms();
  bindControls();

  if (!state.token) {
    showPublicView();
    return;
  }
  try {
    await loadProfile();
    showApp();
    await route();
  } catch (error) {
    if (error.status === 401) await signOut(false);
    else showPublicView();
    showToast(error.message);
  }
}

window.addEventListener("hashchange", route);
start();
