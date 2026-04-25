# Frontend repo — detailed overview

**Purpose:** Chess AI frontend. React 19, TypeScript, Vite 7, Redux Toolkit 2, Tailwind v4, React Router v7. Preconfigured routing, state, theming, API layer; i18n (en, ru, he); mock server for dev.

---

## Run

```bash
npm run dev          # frontend + mock server (concurrently)
npm run dev:frontend # Vite only (e.g. :5173)
npm run dev:mock     # mock server only
npm run build        # build frontend + mock
npm run lint         # eslint
npm run test         # vitest
npm run preview      # vite preview
```

Frontend: http://localhost:5173. Mock API: http://localhost:3001/api; Vite proxies /api/* to mock. See README “Frontend + Mock Server Architecture”.

---

## Package and version

- **package.json:** name "frontend-chess-ai", version PR-based (e.g. 0.0.95). Scripts: dev, dev:frontend, dev:mock, build, build:frontend, build:mock, start, lint, test, preview.
- **Dependencies:** @reduxjs/toolkit, axios, chess.js, react, react-dom, react-router-dom, react-hook-form, @hookform/resolvers, i18next, hls.js, etc. Mock server in mock-server/ (express).

---

## Source layout (src/)

- **main.tsx**, **App.tsx** — entry and root component.
- **app/** — store.ts (Redux), AppShell.tsx, selectors/globalSelectors.ts, hooks (useHeaderIconSize, useFooterResponsiveSize, useDismissablePanel, useAtTop).
- **api/** — http.ts, index.ts, authApi, watchApi, streamsApi, recognitionApi, alertsApi, userApi; interceptors (authInterceptor, refreshInterceptor, errorInterceptor).
- **components/** — Header (Header, Logo, SearchBar, UnicornIcon), FooterNav, MainNav (NavItem, SubMenu), BurgerMenuSheet (BurgerMenuItem), Toast, Modal (LanguageModal, SearchPanel, NotificationsPanel), UiCommon (ThemedChessboard, MiniChessboard, BackButton, ToggleSwitch, Loader, IconButton, IconButtonWithBadge, GradientBg, TempPlaceholder), Watch (TournamentCard, GameCard, TournamentStatusPill, FilterResetButton, DateRangeFilter, TournamentStatusFilter, GameMoveLogs), Recognition (BoardCard, BoardDetails: ChessBoard, MoveLogs, VideoStream, StatusIndicators, utils/groupMoves, types), Streams (StreamsGridView, HlsPlayer), UserProfile (UserProfileHeader, AlertSubscriptionsSection).
- **features/** — auth (authSlice, authThunks, authSelectors, tokenStore, index), watch (watchSlice, watchThunks, watchSelectors, index), streams (streamsSlice), recognition (recognitionSlice, recognitionThunks, recognitionSelectors, utils/formatUtils, index), alertSubscriptions (alertSubscriptionsSlice, alertSubscriptionsThunks, alertSubscriptionsSelectors, index), ui (uiSlice, uiSelectors, index).
- **pages/** — HomePage, LoginPage, SearchResultPage, NotFound; watch (TournamentListPage, TournamentDetailsPage, GameDetailsPage); play (PlayWithHumanPage, PlayWithBotPage); community (CommunityPage); userProfile (UserProfilePage); burgerMenu (BoardDetailsPage, StreamsPage, RecognitionPage), auth (LoginPage).
- **layouts/** — RootLayout, AuthLayout.
- **routes/** — router.tsx, ProtectedRoutes, AdminProtectedRoutes, PublicLoginRoute, Forbidden, NotFound.
- **config/** — routesConstants, mainNavigation, footerNavigation, alertConstants.
- **styles/** — themes.ts (getPrimaryButtonClass, getTextPrimary, getTextMuted, getHeaderGlass, getFooterGlass, getAppGradient, getSheetGradientStyle, getOverlayGradientStyle), themeTokens.css (CSS variables), watchStyles, recognitionStyles, index.css.
- **types/** — index, User, Game, Tournament, Round, Club, Pagination, Ui, AlertSubscription, Recognition, streams; api (WatchApi, RecognitionApi, AlertsApi); schemas (UserProfile, TokenPair, AuthResponse).
- **utils/** — dateUtils, constants, watchTournamentsUtils, browser.
- **core/** — i18next.core.ts (i18n config: fallbackLng "en", detection order localStorage/cookie/navigator/htmlTag, backend loadPath /locales/{{lng}}/{{ns}}.json).

---

## Theme and styling

- **Rule:** Use helpers from `themes.ts`; do not hardcode colors. Tokens in themeTokens.css (e.g. --color-text-primary, --color-text-muted). Theme applied via data-theme="light"|"dark" on html.
- **Helpers:** getPrimaryButtonClass(), getTextPrimary(), getTextMuted(), getHeaderGlass(), getFooterGlass(), getAppGradient(), getSheetGradientStyle(), getOverlayGradientStyle().

---

## i18n

- **Locales:** public/locales/en/translation.json, ru/translation.json, he/translation.json.
- **Config:** src/core/i18next.core.ts — Backend, LanguageDetector, initReactI18next; fallbackLng "en"; detection order localStorage, cookie, navigator, htmlTag; loadPath /locales/{{lng}}/{{ns}}.json.
- **Usage:** useTranslation() → t("key"). Language selector in Burger Menu → Language modal; preference in localStorage.
- **Fonts:** Inter (primary), Rubik (hero), Protest Strike (English decorative). See README “Fonts”.

---

## Tests and quality

- Vitest + React Testing Library. setupTests.ts; components with *.test.tsx (e.g. Forbidden, Toast, ToggleSwitch, TournamentCard, StreamsGridView, authApi).
- Import alias: @/* → src/. ESLint, TypeScript strict.

---

## Source

Repo README for Theme & Color Tokens guide, i18n, Frontend + Mock Server Architecture, and full layout. .cursor/rules/ for project conventions.
