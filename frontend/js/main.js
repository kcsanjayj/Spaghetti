import * as store from "./store.js";
import * as chat from "./chat.js";
import * as docs from "./docs.js";
import * as picker from "./picker.js";
import { hydrate } from "./icons.js";
import { initTheme } from "./theme.js";
import { $ } from "./util.js";

store.load();
hydrate();
initTheme($("#themeBtn"));
picker.init();
docs.init();
chat.init();
picker.ensureModel(); // picks a model automatically, or opens the menu with setup help
