/* V2C profile management. All writes use the validated HA backend. */
const TEXT = {
  en: {
    menu: "Menu",
    title: "V2C profiles",
    charger: "Charger",
    profile: "Profile",
    refresh: "Refresh",
    weekdays: "Weekdays",
    weekend: "Weekend",
    active: "Active",
    inactive: "Inactive",
    unknown: "Unknown",
    start: "Start",
    end: "End",
    mode: "Mode",
    priority: "Battery priority",
    allow: "Allow battery use",
    save: "Save",
    cancel: "Cancel",
    home: "Home",
    vehicle: "Vehicle",
    empty: "No profiles returned by V2C Cloud.",
    noDevices: "No Cloud charger is configured.",
    saved: "Operation confirmed by Cloud read-back.",
    profile_conflict:
      "The profile changed. Refresh and review it before editing again.",
    save_unconfirmed:
      "Operation unconfirmed. Refresh and inspect Cloud state before trying again. No automatic retry was sent.",
    profiles_unavailable:
      "Profiles unavailable. Refresh and check your V2C Cloud connection.",
    modes: [
      "PV + minimum",
      "Exclusive PV",
      "Grid + PV",
      "No charging",
      "No injection / isolated",
    ],
    create: "Create new profile",
    activate: "Activate",
    remove: "Delete",
    add: "Add interval",
    name: "New profile name",
    advanced: "Advanced phase values",
    activationNote:
      "This applies the saved profile to the charger. It may affect charging. No separate start command is sent.",
    deleteNote: "Delete this inactive profile?",
    deleteActive: "Activate another profile before deleting this one.",
    invalid_profile:
      "Invalid or unsupported draft: check hours, overlaps, required power and profile name. Refresh if the remote schema changed.",
    removeInterval: "Remove interval",
    discard: "Discard unsaved schedule changes?",
    changes: "Save changes",
    template:
      "The new profile starts with this saved schedule. You can edit it before saving.",
    about: "Information about",
    documentation: "V2C documentation",
    adjust: "Adjust",
    contracted: "Contracted power",
    deviation: "Power deviation",
    discharge: "Battery discharge",
    modesHelp: [
      "Prioritises solar surplus. If it is insufficient, the e-Charger charges at the configured minimum current.",
      "Charges using solar surplus only. The V2C explanation specifies a surplus above 1.5 kW before the vehicle charges.",
      "Uses all available power to achieve the maximum charging speed.",
      "Prevents vehicle charging during this time slot.",
      "For off-grid installations or installations with grid export disabled. Similar to PV + minimum: uses available solar energy and lets you adjust minimum battery discharge power. The V2C explanation states a minimum of 260 W.",
    ],
    contractedHelp:
      "The grid power contracted for this time slot, in kW. The charger adjusts vehicle charging to the home's consumption. This is not a fixed vehicle charging power.",
    deviationHelp:
      "Positive values allow the selected amount of grid consumption in watts; negative values require the corresponding surplus. Values are rounded to the nearest 100 W, or to 0 when the deviation is between -50 W and +50 W inclusive.",
    dischargeHelp:
      "Allowed battery discharge power for this time slot, in watts, in isolated mode. The portal accepts 0–10000 W; firmware capabilities may differ. Available on Trydan/Trydan Pro or an already observed isolated schedule.",
    guide: "https://v2charge.com/support/power-control/customization/",
    faq: "https://v2charge.com/fr/base-de-connaissances-v2c-pour-chatbot/",
  },
  fr: {
    menu: "Menu",
    title: "Profils V2C",
    charger: "Borne",
    profile: "Profil",
    refresh: "Actualiser",
    weekdays: "Semaine",
    weekend: "Week-end",
    active: "Actif",
    inactive: "Inactif",
    unknown: "Inconnu",
    start: "Début",
    end: "Fin",
    mode: "Mode",
    priority: "Priorité batterie",
    allow: "Autoriser la batterie",
    save: "Enregistrer",
    cancel: "Annuler",
    home: "Maison",
    vehicle: "Voiture",
    empty: "V2C Cloud n’a renvoyé aucun profil.",
    noDevices: "Aucune borne Cloud configurée.",
    saved: "Opération confirmée par relecture Cloud.",
    profile_conflict:
      "Le profil a changé. Actualise-le et vérifie-le avant une nouvelle modification.",
    save_unconfirmed:
      "Opération non confirmée. Actualise et vérifie l’état Cloud avant une nouvelle tentative. Aucun nouvel essai automatique n’a été envoyé.",
    profiles_unavailable:
      "Profils indisponibles. Actualise et vérifie la connexion V2C Cloud.",
    modes: [
      "PV + puissance minimale",
      "PV exclusif",
      "Réseau + PV",
      "Sans charge",
      "Sans injection ou isolé",
    ],
    create: "Créer un nouveau profil",
    activate: "Activer",
    remove: "Supprimer",
    add: "Ajouter un créneau",
    name: "Nom du nouveau profil",
    advanced: "Intensités par phase — avancé",
    activationNote:
      "Cette action applique le profil enregistré à la borne et peut affecter la recharge. Aucune commande de démarrage distincte n’est envoyée.",
    deleteNote: "Supprimer ce profil inactif ?",
    deleteActive: "Active un autre profil avant de supprimer celui-ci.",
    invalid_profile:
      "Brouillon invalide ou non pris en charge : vérifie horaires, chevauchements, puissance requise et nom du profil. Actualise si son format Cloud a changé.",
    removeInterval: "Supprimer le créneau",
    discard: "Abandonner les modifications du planning non enregistrées ?",
    changes: "Enregistrer les modifications",
    template:
      "Le nouveau profil reprend ce planning enregistré. Vous pouvez le modifier avant de l’enregistrer.",
    about: "Informations sur",
    documentation: "Documentation V2C",
    adjust: "Ajuster",
    contracted: "Puissance souscrite",
    deviation: "Déviation de puissance",
    discharge: "Décharge de la batterie",
    modesHelp: [
      "L’e-Charger privilégie le surplus solaire. S’il est insuffisant, la recharge se fait à l’intensité minimale définie.",
      "Recharge uniquement avec le surplus solaire. L’explication V2C indique un excédent supérieur à 1,5 kW pour que la voiture recharge.",
      "L’e-Charger fournit toute la puissance disponible pour atteindre la vitesse de recharge maximale.",
      "Empêche la recharge du véhicule pendant ce créneau.",
      "Pour les installations isolées du réseau ou dont l’injection est désactivée. Fonctionnement similaire à PV + puissance minimale : utilise le solaire disponible et permet d’ajuster la puissance minimale de décharge des batteries. L’explication V2C mentionne un minimum de 260 W.",
    ],
    contractedHelp:
      "Puissance du contrat électrique pour ce créneau, en kW. La borne adapte la recharge à la consommation du logement. Ce n’est pas une puissance de recharge fixe du véhicule.",
    deviationHelp:
      "Les valeurs positives permettront une consommation réseau correspondant à la valeur sélectionnée en watts, tandis que les valeurs négatives forceront un dépassement de ces watts. Les watts seront arrondis à la centaine la plus proche, ou à 0 si l’écart est inférieur ou égal à 50 W (ou -50 W).",
    dischargeHelp:
      "Puissance de décharge de la batterie autorisée pendant ce créneau, en watts, en mode isolé. Le portail accepte 0 à 10000 W ; les capacités du firmware peuvent différer. Disponible sur Trydan/Trydan Pro ou si un planning isolé est déjà présent.",
    guide:
      "https://v2charge.com/fr/support/controle-puissance/personnalisation/",
    faq: "https://v2charge.com/fr/base-de-connaissances-v2c-pour-chatbot/",
  },
  it: {
    menu: "Menu",
    title: "Profili V2C",
    charger: "Caricatore",
    profile: "Profilo",
    refresh: "Aggiorna",
    weekdays: "Giorni feriali",
    weekend: "Fine settimana",
    active: "Attivo",
    inactive: "Inattivo",
    unknown: "Sconosciuto",
    start: "Inizio",
    end: "Fine",
    mode: "Modalità",
    priority: "Priorità batteria",
    allow: "Consenti batteria",
    save: "Salva",
    cancel: "Annulla",
    home: "Casa",
    vehicle: "Veicolo",
    empty: "Nessun profilo restituito da V2C Cloud.",
    noDevices: "Nessun caricatore Cloud configurato.",
    saved: "Operazione confermata dal Cloud.",
    profile_conflict:
      "Il profilo è cambiato. Aggiorna e verifica prima di modificare.",
    save_unconfirmed:
      "Operazione non confermata. Aggiorna e verifica il Cloud prima di riprovare. Nessun tentativo automatico.",
    profiles_unavailable:
      "Profili non disponibili. Aggiorna e verifica la connessione Cloud.",
    modes: [
      "FV + minimo",
      "Solo FV",
      "Rete + FV",
      "Nessuna ricarica",
      "Senza immissione / isolato",
    ],
    create: "Crea nuovo profilo",
    activate: "Attiva",
    remove: "Elimina",
    add: "Aggiungi fascia",
    name: "Nome del nuovo profilo",
    advanced: "Intensità per fase — avanzate",
    activationNote:
      "Applica il profilo salvato al caricatore e può influire sulla ricarica. Nessun comando di avvio separato.",
    deleteNote: "Eliminare questo profilo inattivo?",
    deleteActive: "Attiva un altro profilo prima di eliminarlo.",
    invalid_profile:
      "Bozza non valida: verifica orari, sovrapposizioni, potenza e nome.",
    removeInterval: "Elimina fascia",
    discard: "Scartare le modifiche agli orari non salvate?",
    changes: "Salva modifiche",
    template:
      "Il nuovo profilo parte dagli orari salvati, modificabili prima del salvataggio.",
    about: "Informazioni su",
    documentation: "Documentazione V2C",
    adjust: "Regola",
    contracted: "Potenza contrattuale",
    deviation: "Deviazione di potenza",
    discharge: "Scarica della batteria",
    modesHelp: [
      "Privilegia il surplus solare. Se non è sufficiente, l’e-Charger ricarica all’intensità minima configurata.",
      "Ricarica solo con il surplus solare. La spiegazione V2C indica un surplus superiore a 1,5 kW prima che il veicolo ricarichi.",
      "L’e-Charger utilizza tutta la potenza disponibile per raggiungere la massima velocità di ricarica.",
      "Impedisce la ricarica del veicolo durante questa fascia.",
      "Per impianti isolati dalla rete o con immissione disabilitata. Simile a FV + minimo: usa l’energia solare disponibile e permette di regolare la potenza minima di scarica delle batterie. La spiegazione V2C indica un minimo di 260 W.",
    ],
    contractedHelp:
      "Potenza contrattuale della rete per questa fascia, in kW. Il caricatore adatta la ricarica ai consumi della casa. Non è una potenza di ricarica fissa del veicolo.",
    deviationHelp:
      "I valori positivi consentono un prelievo dalla rete pari al valore selezionato in watt; quelli negativi richiedono il corrispondente surplus. I valori vengono arrotondati al centinaio di watt più vicino, oppure a 0 se lo scostamento è compreso tra -50 W e +50 W inclusi.",
    dischargeHelp:
      "Potenza di scarica della batteria consentita in questa fascia, in watt, nella modalità isolata. Il portale accetta 0–10000 W; le capacità del firmware possono variare. Disponibile su Trydan/Trydan Pro o con orari isolati già presenti.",
    guide:
      "https://v2charge.com/it/supporto/controllo-potenza/personalizzazione/",
    faq: "https://v2charge.com/fr/base-de-connaissances-v2c-pour-chatbot/",
  },
  es: {
    menu: "Menú",
    title: "Perfiles V2C",
    charger: "Cargador",
    profile: "Perfil",
    refresh: "Actualizar",
    weekdays: "Entre semana",
    weekend: "Fin de semana",
    active: "Activo",
    inactive: "Inactivo",
    unknown: "Desconocido",
    start: "Inicio",
    end: "Fin",
    mode: "Modo",
    priority: "Prioridad de batería",
    allow: "Permitir batería",
    save: "Guardar",
    cancel: "Cancelar",
    home: "Casa",
    vehicle: "Vehículo",
    empty: "V2C Cloud no devolvió perfiles.",
    noDevices: "Ningún cargador Cloud configurado.",
    saved: "Operación confirmada por el Cloud.",
    profile_conflict:
      "El perfil ha cambiado. Actualiza y comprueba antes de editar.",
    save_unconfirmed:
      "Operación no confirmada. Actualiza y comprueba el Cloud antes de reintentar. Sin reintentos automáticos.",
    profiles_unavailable:
      "Perfiles no disponibles. Actualiza y comprueba la conexión Cloud.",
    modes: [
      "FV + mínimo",
      "Solo FV",
      "Red + FV",
      "Sin carga",
      "Sin inyección o aislada",
    ],
    create: "Crear nuevo perfil",
    activate: "Activar",
    remove: "Eliminar",
    add: "Añadir tramo",
    name: "Nombre del nuevo perfil",
    advanced: "Intensidades por fase — avanzado",
    activationNote:
      "Aplica el perfil guardado al cargador y puede afectar a la carga. No envía un comando de inicio separado.",
    deleteNote: "¿Eliminar este perfil inactivo?",
    deleteActive: "Activa otro perfil antes de eliminarlo.",
    invalid_profile:
      "Borrador no válido: comprueba horarios, solapamientos, potencia y nombre.",
    removeInterval: "Eliminar tramo",
    discard: "¿Descartar cambios de horarios sin guardar?",
    changes: "Guardar cambios",
    template:
      "El nuevo perfil parte de estos horarios guardados, editables antes de guardar.",
    about: "Información sobre",
    documentation: "Documentación V2C",
    adjust: "Ajustar",
    contracted: "Potencia contratada",
    deviation: "Desviación de potencia",
    discharge: "Descarga de la batería",
    modesHelp: [
      "Prioriza los excedentes solares. Si son insuficientes, el e-Charger carga a la intensidad mínima configurada.",
      "Carga únicamente con excedentes solares. La explicación V2C indica un excedente superior a 1,5 kW antes de que el vehículo cargue.",
      "El e-Charger utiliza toda la potencia disponible para alcanzar la máxima velocidad de carga.",
      "Impide cargar el vehículo durante este tramo.",
      "Para instalaciones aisladas de la red o con vertido desactivado. Similar a FV + mínimo: usa la energía solar disponible y permite ajustar la potencia mínima de descarga de las baterías. La explicación V2C menciona un mínimo de 260 W.",
    ],
    contractedHelp:
      "Potencia de red contratada para este tramo, en kW. El cargador adapta la carga al consumo de la vivienda. No es una potencia de carga fija del vehículo.",
    deviationHelp:
      "Los valores positivos permiten un consumo de red correspondiente al valor seleccionado en vatios; los negativos exigen el excedente correspondiente. Los valores se redondean a la centena de vatios más cercana, o a 0 si la desviación está entre -50 W y +50 W, ambos incluidos.",
    dischargeHelp:
      "Potencia de descarga de batería permitida durante este tramo, en vatios, en modo aislado. El portal acepta 0–10000 W; las capacidades del firmware pueden variar. Disponible en Trydan/Trydan Pro o con un horario aislado existente.",
    guide: "https://v2charge.com/es/soporte/control-potencia/personalizacion/",
    faq: "https://v2charge.com/es/fuente-de-conocimiento-v2c-para-chatbot/",
  },
};

function node(tag, text, parent) {
  const element = document.createElement(tag);
  if (text !== undefined) element.textContent = text;
  parent?.append(element);
  return element;
}
function schedule(value, type) {
  try {
    const parsed = JSON.parse(value);
    return parsed && parsed.type === type && Array.isArray(parsed.tram)
      ? parsed.tram
      : [];
  } catch {
    return [];
  }
}
function decimalShift(value, places) {
  // Shift decimal digits without introducing binary floating-point display noise.
  const [coefficient, exponent = "0"] = String(value).toLowerCase().split("e");
  const negative = coefficient.startsWith("-");
  const [whole, fraction = ""] = coefficient.replace("-", "").split(".");
  const digits = whole + fraction;
  const point = whole.length + Number(exponent) + places;
  let text =
    point <= 0
      ? `0.${"0".repeat(-point)}${digits}`
      : point >= digits.length
        ? digits + "0".repeat(point - digits.length)
        : `${digits.slice(0, point)}.${digits.slice(point)}`;
  text = text.replace(/^0+(?=\d)/, "");
  if (text.includes(".")) text = text.replace(/0+$/, "").replace(/\.$/, "");
  return negative ? `-${text}` : text;
}

class V2CProfilesPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._fieldId = 0;
    this._devices = [];
    this._profiles = [];
    this._device = 0;
    this._name = "";
    this._busy = false;
    this._dirty = false;
    this._beforeUnload = (event) => {
      if (this._dirty) {
        event.preventDefault();
        event.returnValue = "";
      }
    };
  }
  connectedCallback() {
    window.addEventListener("beforeunload", this._beforeUnload);
  }
  disconnectedCallback() {
    window.removeEventListener("beforeunload", this._beforeUnload);
  }
  _leaveDraft() {
    return !this._dirty || window.confirm(this._t.discard);
  }
  set hass(value) {
    this._hass = value;
    this._t = TEXT[value.language?.split("-")[0]] || TEXT.en;
    if (!this._started) {
      this._started = true;
      this._loadDevices();
    }
  }
  _api(type, extra = {}) {
    const device = this._devices[this._device];
    return this._hass.callWS({
      type: `v2c_cloud/profiles/${type}`,
      ...(device
        ? { entry_id: device.entry_id, device_id: device.device_id }
        : {}),
      ...extra,
    });
  }
  async _loadDevices() {
    this._busy = true;
    this._render();
    try {
      this._devices = await this._hass.callWS({
        type: "v2c_cloud/profiles/devices",
      });
      if (this._devices.length) await this._load();
    } catch (error) {
      this._message = this._t[error.code] || this._t.profiles_unavailable;
    } finally {
      this._busy = false;
      this._render();
    }
  }
  async _load(preservePlanning = false) {
    this._busy = true;
    if (!preservePlanning) {
      this._planning = undefined;
      this._dirty = false;
    }
    this._profiles = []; // A failed refresh must not leave stale edit controls.
    this._render();
    try {
      this._profiles = await this._api("list");
      if (!this._profiles.some((item) => item.profile.name === this._name)) {
        this._name =
          (
            this._profiles.find((item) => item.profile.active === true) ||
            this._profiles[0]
          )?.profile.name || "";
      }
    } catch (error) {
      this._message = this._t[error.code] || this._t.profiles_unavailable;
    } finally {
      this._busy = false;
      this._render();
    }
  }
  _button(text, parent, callback) {
    const button = node("button", text, parent);
    button.disabled = this._busy;
    button.addEventListener("click", callback);
    return button;
  }
  _info(parent, title, paragraphs, source) {
    const group = node("span", undefined, parent);
    group.className = "help";
    const button = this._button("i", group, () => show());
    button.type = "button";
    button.className = "info";
    button.setAttribute("aria-label", `${this._t.about} ${title}`);
    button.setAttribute("aria-expanded", "false");
    const tip = node("div", undefined, group);
    tip.className = "tooltip";
    tip.id = `v2c-help-${++this._fieldId}`;
    tip.hidden = true;
    tip.setAttribute("role", "tooltip");
    button.setAttribute("aria-controls", tip.id);
    button.setAttribute("aria-describedby", tip.id);
    paragraphs.forEach((text) => node("p", text, tip));
    const link = node("a", this._t.documentation, tip);
    link.href = source;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    let hideTimer;
    const show = () => {
      clearTimeout(hideTimer);
      if (this._hideHelp !== hide) this._hideHelp?.();
      this._hideHelp = hide;
      const rect = button.getBoundingClientRect(),
        width = Math.min(380, window.innerWidth - 24);
      tip.style.width = `${width}px`;
      tip.style.left = `${Math.max(12, Math.min(rect.left, window.innerWidth - width - 12))}px`;
      tip.hidden = false;
      const below = Math.max(0, window.innerHeight - rect.bottom - 20),
        above = Math.max(0, rect.top - 20);
      const useBelow = tip.scrollHeight + 2 <= below || below >= above;
      tip.style.maxHeight = `${useBelow ? below : above}px`;
      const height = tip.getBoundingClientRect().height;
      tip.style.top = `${useBelow ? rect.bottom + 8 : rect.top - height - 8}px`;
      button.setAttribute("aria-expanded", "true");
    };
    const hide = () => {
      clearTimeout(hideTimer);
      tip.hidden = true;
      button.setAttribute("aria-expanded", "false");
    };
    group.addEventListener("mouseenter", show);
    group.addEventListener("mouseleave", () => {
      if (!group.contains(this.shadowRoot.activeElement))
        hideTimer = setTimeout(hide, 200);
    });
    button.addEventListener("focus", show);
    group.addEventListener("focusout", (event) => {
      if (!group.contains(event.relatedTarget)) hide();
    });
    group.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        event.preventDefault();
        hide();
      }
    });
  }
  _field(parent, title, area, help, source) {
    const field = node("div", undefined, parent);
    field.className = "field";
    field.style.gridArea = area;
    const caption = node("div", undefined, field);
    caption.className = "field-title";
    const label = node("label", title, caption);
    label.htmlFor = `v2c-field-${++this._fieldId}`;
    if (help) this._info(caption, title, help, source);
    return { field, id: label.htmlFor };
  }
  _render() {
    const t = this._t;
    const root = this.shadowRoot;
    root.replaceChildren();
    const style = node("style", undefined, root);
    style.textContent = `
      :host{display:block;color:var(--primary-text-color,#212121);background:var(--primary-background-color,#fafafa);min-height:100vh;font-family:var(--paper-font-body1_-_font-family,sans-serif)}
      *{box-sizing:border-box}header{display:flex;align-items:center;gap:16px;padding:12px 24px;background:var(--app-header-background-color,var(--primary-color,#03a9f4));color:var(--app-header-text-color,white)}
      header button{background:transparent;border:none;font-size:24px}h1{font-size:22px;margin:0}h2{font-size:20px}main{max-width:1200px;margin:auto;padding:24px}
      .toolbar{display:flex;gap:12px;flex-wrap:wrap;align-items:end}.toolbar>label{flex:1;min-width:200px}label{display:flex;flex-direction:column;gap:8px;font-size:14px}
      select,button,input[type=number],input[type=text]{font:inherit;min-height:44px;padding:10px 12px;border-radius:8px;border:1px solid var(--divider-color,#dddddd);color:inherit;background:var(--card-background-color,#ffffff)}
      select,input[type=number],input[type=text]{width:100%;min-width:0}button{cursor:pointer}button:disabled{opacity:.5;cursor:default}.primary{background:var(--primary-color,#03a9f4);color:var(--text-primary-color,white);border-color:transparent}
      .icon{width:44px;padding:10px;display:grid;place-items:center}.icon svg{width:24px;height:24px;fill:currentColor}.actions{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin-top:20px}.actions .danger{margin-inline-start:auto;color:var(--error-color,#db4437)}
      section{margin-top:24px;background:var(--card-background-color,#ffffff);padding:20px;border-radius:12px;border:1px solid var(--divider-color,#dddddd)}fieldset{display:grid;grid-template-columns:90px 90px 230px minmax(200px,1fr) 176px 44px;grid-template-areas:"start end mode power battery remove";align-items:end;gap:12px;margin:12px 0;padding:12px;border:1px solid var(--divider-color,#dddddd);border-radius:10px}legend{font-size:14px;padding:0 8px;color:var(--secondary-text-color,#727272)}
      .field{min-width:0;display:flex;flex-direction:column;gap:8px}.field-title{display:flex;align-items:center;gap:6px;min-height:20px}.field-title label{display:block}.battery{flex-direction:row;align-items:center;grid-area:battery;min-height:44px;gap:8px;white-space:nowrap}input[type=checkbox]{width:22px;height:22px;accent-color:var(--primary-color,#03a9f4);flex-shrink:0}.remove-slot{justify-self:end;grid-area:remove;color:var(--error-color,#db4437)}
      .form-actions{position:sticky;bottom:12px;display:flex;gap:12px;padding:12px;margin-top:20px;background:var(--card-background-color,#ffffff);border:1px solid var(--divider-color,#dddddd);border-radius:12px;box-shadow:0 2px 8px #0002}.form-actions[hidden]{display:none}.form-actions button:first-child{margin-inline-start:auto}
      .help{display:inline-flex}.info{font:600 12px/1 sans-serif;min-height:24px;width:24px;padding:0;border-radius:50%;color:var(--secondary-text-color,#727272)}.tooltip{position:fixed;z-index:100;overflow:auto;padding:12px 16px;border:1px solid var(--divider-color,#dddddd);border-radius:10px;background:var(--card-background-color,#ffffff);color:var(--primary-text-color,#212121);box-shadow:0 4px 20px #0004;font-size:14px;line-height:1.5}.tooltip[hidden]{display:none}.tooltip p{margin:8px 0}.tooltip a{color:var(--primary-color,#03a9f4)}.power-inputs{display:flex;align-items:center;gap:8px}.power-inputs input[type=number]{flex:1;min-width:76px}.power-inputs.with-slider input[type=number]{flex:0 0 96px;width:96px;min-width:0}.power-inputs input[type=range]{flex:1;min-width:80px;width:100%;accent-color:var(--primary-color,#03a9f4)}.remove-slot svg{width:20px;height:20px;fill:currentColor}
      @media(max-width:1000px) and (min-width:751px){fieldset{grid-template-columns:90px 90px 1fr 40px;grid-template-areas:"start end mode mode" "power power battery remove"}}
      details{margin-top:16px;color:var(--secondary-text-color,#727272)}dialog{max-width:480px;width:calc(100% - 32px);max-height:90vh;overflow:auto;border:1px solid var(--divider-color,#dddddd);border-radius:16px;color:var(--primary-text-color,#212121);background:var(--card-background-color,#ffffff);padding:24px}dialog::backdrop{background:#0006}dialog p{line-height:1.5}dialog>button{margin:8px 8px 0 0}dialog.editor{max-width:1000px}.profile-name{margin-top:20px;width:100%}.profile-name input{width:100%}button:focus-visible,select:focus-visible,input:focus-visible{outline:2px solid var(--primary-color,#03a9f4);outline-offset:2px}
      @media(max-width:750px){main{padding:12px}section{padding:12px}fieldset{grid-template-columns:minmax(0,1fr) minmax(0,1fr);grid-template-areas:"start end" "mode mode" "power power" "battery remove";gap:12px}.toolbar>label{min-width:100%}.form-actions{bottom:4px}}@media(max-width:350px){.battery{white-space:normal}}
    `;
    const header = node("header", undefined, root);
    this._button("☰", header, () =>
      this.dispatchEvent(
        new Event("hass-toggle-menu", { bubbles: true, composed: true }),
      ),
    ).setAttribute("aria-label", t.menu);
    node("h1", t.title, header);
    const main = node("main", undefined, root);
    main.setAttribute("aria-busy", String(this._busy));
    const toolbar = node("div", undefined, main);
    toolbar.className = "toolbar";
    const chargerLabel = node("label", t.charger, toolbar);
    const charger = node("select", undefined, chargerLabel);
    this._devices.forEach((device, index) => {
      const label =
        device.name && device.name !== device.device_id
          ? `${device.name} · ${device.device_id}`
          : device.device_id;
      const option = node("option", label, charger);
      option.value = String(index);
    });
    charger.value = String(this._device);
    charger.disabled = this._busy;
    charger.addEventListener("change", () => {
      if (!this._leaveDraft()) {
        charger.value = String(this._device);
        return;
      }
      this._device = Number(charger.value);
      this._name = "";
      this._message = "";
      this._load();
    });
    const profileLabel = node("label", t.profile, toolbar);
    const profiles = node("select", undefined, profileLabel);
    this._profiles.forEach(({ profile }) => {
      const status =
        profile.active === true
          ? t.active
          : profile.active === false
            ? t.inactive
            : t.unknown;
      const option = node("option", `${profile.name} · ${status}`, profiles);
      option.value = profile.name;
    });
    profiles.value = this._name;
    profiles.disabled = this._busy;
    profiles.addEventListener("change", () => {
      if (!this._leaveDraft()) {
        profiles.value = this._name;
        return;
      }
      this._name = profiles.value;
      this._planning = undefined;
      this._dirty = false;
      this._message = "";
      this._render();
    });
    const selected = this._profiles.find(
      (item) => item.profile.name === this._name,
    );
    const activate = this._button(
      selected?.profile.active === true ? t.active : t.activate,
      toolbar,
      () => {
        if (this._leaveDraft()) this._actionDialog(selected, "activate");
      },
    );
    activate.className = "primary";
    activate.disabled =
      this._busy ||
      !selected ||
      selected.editable === false ||
      selected.profile.active === true;
    const refresh = this._button("", toolbar, () => {
      if (!this._leaveDraft()) return;
      this._message = "";
      this._devices.length ? this._load() : this._loadDevices();
    });
    refresh.className = "icon";
    refresh.title = t.refresh;
    refresh.setAttribute("aria-label", t.refresh);
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("aria-hidden", "true");
    const path = document.createElementNS(svg.namespaceURI, "path");
    path.setAttribute(
      "d",
      "M17.65 6.35A7.95 7.95 0 0 0 12 4a8 8 0 0 0-8 8h2a6 6 0 0 1 10.24-4.24L13 11h7V4l-2.35 2.35zM18 12a6 6 0 0 1-10.24 4.24L11 13H4v7l2.35-2.35A7.95 7.95 0 0 0 12 20a8 8 0 0 0 8-8h-2z",
    );
    svg.append(path);
    refresh.append(svg);
    const status = node("p", this._busy ? "…" : this._message || "", main);
    status.setAttribute("role", "status");
    if (!this._devices.length) {
      if (!this._busy && !this._message) node("p", t.noDevices, main);
      return;
    }
    if (!selected) {
      if (!this._busy && !this._message) node("p", t.empty, main);
      return;
    }
    const actions = node("div", undefined, main);
    actions.className = "actions";
    this._button(t.create, actions, () => {
      if (!this._leaveDraft()) return;
      this._planning = undefined;
      this._dirty = false;
      this._render();
      this._editor(selected, true);
    }).disabled = this._busy || selected.editable === false;
    const remove = this._button(t.remove, actions, () => {
      if (this._leaveDraft()) this._actionDialog(selected, "delete");
    });
    remove.className = "danger";
    remove.disabled =
      this._busy ||
      selected.editable === false ||
      selected.profile.active !== false;
    if (selected.profile.active !== false) remove.title = t.deleteActive;
    if (selected.editable !== false) this._editor(selected, false, main);
    else node("p", t.invalid_profile, main);
  }
  _actionDialog(selected, action) {
    if (this._busy) return;
    const t = this._t;
    const dialog = node("dialog", undefined, this.shadowRoot);
    dialog.setAttribute(
      "aria-label",
      t[action === "activate" ? "activate" : "remove"],
    );
    node(
      "h2",
      `${t[action === "activate" ? "activate" : "remove"]} · ${selected.profile.name}`,
      dialog,
    );
    node("p", action === "activate" ? t.activationNote : t.deleteNote, dialog);
    this._button(t.cancel, dialog, () => dialog.close());
    this._button(
      t[action === "activate" ? "activate" : "remove"],
      dialog,
      () => {
        dialog.close();
        this._manage(selected, { action });
      },
    );
    dialog.addEventListener("close", () => dialog.remove());
    dialog.showModal();
  }
  _editor(selected, create, parent) {
    if (this._busy && !parent) return;
    const t = this._t;
    const originals = [
      schedule(selected.profile.powerweekday, 0),
      schedule(selected.profile.powerweekend, 1),
    ];
    const fresh = () =>
      originals.map((items, group) =>
        items.map((item, source) => ({ group, source, values: {} })),
      );
    if (
      !create &&
      (!this._planning || this._planning.name !== selected.profile.name)
    )
      this._planning = { name: selected.profile.name, entries: fresh() };
    const entries = create ? fresh() : this._planning.entries;
    const dialog = create
      ? node("dialog", undefined, this.shadowRoot)
      : undefined;
    if (dialog) {
      dialog.className = "editor";
      dialog.setAttribute("aria-label", t.create);
    }
    const form = node("form", undefined, dialog || parent);
    if (create) {
      node("h2", t.create, form);
      node("p", t.template, form);
    }
    let name;
    if (create) {
      const label = node("label", t.name, form);
      label.className = "profile-name";
      name = node("input", undefined, label);
      name.type = "text";
      name.required = true;
    }
    const content = node("div", undefined, form);
    let save, actions;
    const changed = () => {
      if (!create) {
        this._dirty = true;
        actions.hidden = false;
        save.disabled = this._busy;
      }
    };
    const redraw = () => {
      content.replaceChildren();
      entries.forEach((items, group) => {
        const section = node("section", undefined, content);
        node("h2", group === 0 ? t.weekdays : t.weekend, section);
        items.forEach((entry, index) => {
          const original = originals[group][entry.source];
          const values = entry.values;
          const mode = values.mode ?? original.charge_fv_mode;
          const fieldset = node("fieldset", undefined, section);
          fieldset.disabled = this._busy;
          node("legend", `#${index + 1}`, fieldset);
          for (const [key, title, area] of [
            ["hourStart", t.start, "start"],
            ["hourEnd", t.end, "end"],
          ]) {
            const { field, id } = this._field(fieldset, title, area);
            const input = node("select", undefined, field);
            input.id = id;
            input.required = true;
            const blank = node("option", "—", input);
            blank.value = "";
            blank.disabled = true;
            for (let hour = 0; hour <= 24; hour++) {
              const option = node(
                "option",
                `${String(hour).padStart(2, "0")}:00`,
                input,
              );
              option.value = String(hour);
            }
            const value = String(values[key] ?? original[key] ?? "");
            // Preserve fractional hours already returned by Cloud, without rounding.
            if (
              value !== "" &&
              Number.isFinite(Number(value)) &&
              !Number.isInteger(Number(value))
            ) {
              const option = node("option", `${value} h`, input);
              option.value = value;
            }
            input.value = value;
            input.addEventListener("change", () => {
              values[key] = input.value;
              changed();
            });
          }
          const modeField = this._field(
            fieldset,
            t.mode,
            "mode",
            t.modes.map((name, index) => `${name} : ${t.modesHelp[index]}`),
            t.guide,
          );
          const select = node("select", undefined, modeField.field);
          select.id = modeField.id;
          t.modes.forEach((title, value) => {
            const option = node("option", title, select);
            option.value = String(value);
            if (
              value === 4 &&
              selected.supports_isolated === false &&
              original.charge_fv_mode !== 4
            ) {
              option.disabled = true;
              option.title = t.dischargeHelp;
            }
          });
          select.value = String(mode);
          select.addEventListener("change", () => {
            values.mode = Number(select.value);
            delete values.power_value;
            delete values.battery_discharge_w;
            delete values.allow_battery;
            delete values.priority;
            if (values.mode === 1) values.power_value = "0";
            changed();
            redraw();
          });
          if ([0, 1, 2, 4].includes(mode)) {
            const title =
              mode === 1
                ? `${t.deviation} (W)`
                : mode === 4
                  ? `${t.discharge} (W)`
                  : `${t.contracted} (kW)`;
            const help =
              mode === 1
                ? t.deviationHelp
                : mode === 4
                  ? t.dischargeHelp
                  : t.contractedHelp;
            const powerField = this._field(
              fieldset,
              title,
              "power",
              [help],
              mode === 1 ? t.faq : t.guide,
            );
            const controls = node("div", undefined, powerField.field);
            controls.className = "power-inputs";
            const input = node("input", undefined, controls);
            input.id = powerField.id;
            input.type = "number";
            input.step = "any";
            {
              const key = mode === 4 ? "battery_discharge_w" : "power_value";
              input.required = true;
              input.min = mode === 1 ? "-10000" : "0";
              input.max = [1, 4].includes(mode) ? "10000" : "5000";
              input.value =
                values[key] ??
                (mode === original.charge_fv_mode &&
                typeof original.power === "number"
                  ? decimalShift(original.power, [1, 4].includes(mode) ? 2 : -1)
                  : "");
              let slider;
              if (mode === 1) {
                controls.classList.add("with-slider");
                slider = node("input", undefined, controls);
                slider.type = "range";
                slider.min = "-5000";
                slider.max = "5000";
                slider.step = "100";
                slider.setAttribute("aria-label", `${t.adjust} ${t.deviation}`);
                slider.value = input.value || "0";
                slider.addEventListener("input", () => {
                  input.value = slider.value;
                  values[key] = input.value;
                  changed();
                });
              }
              input.addEventListener("input", () => {
                values[key] = input.value;
                if (slider && input.validity.valid) slider.value = input.value;
                changed();
              });
            }
          }
          if ([0, 2].includes(mode) && [0, 1].includes(original.bat_mode)) {
            const label = node("label", t.allow, fieldset);
            label.className = "battery";
            const input = node("input", undefined, label);
            input.type = "checkbox";
            input.checked = values.allow_battery ?? original.bat_mode === 0;
            input.addEventListener("change", () => {
              if (
                create ||
                entry.source !== index ||
                mode !== original.charge_fv_mode ||
                items.length !== originals[group].length
              ) {
                values.allow_battery = input.checked;
                changed();
                return;
              }
              delete values.allow_battery;
              this._save(selected, group, entry.source, input.checked);
            });
          }
          if (mode === 1 && [0, 1].includes(original.bat_prio)) {
            const priorityField = this._field(fieldset, t.priority, "battery");
            const select = node("select", undefined, priorityField.field);
            select.id = priorityField.id;
            for (const [value, title] of [
              ["home", t.home],
              ["vehicle", t.vehicle],
            ]) {
              const option = node("option", title, select);
              option.value = value;
            }
            select.value =
              values.priority ?? (original.bat_prio === 0 ? "home" : "vehicle");
            select.addEventListener("change", () => {
              values.priority = select.value;
              changed();
            });
          }
          const remove = this._button("", fieldset, () => {
            items.splice(index, 1);
            changed();
            redraw();
          });
          remove.className = "remove-slot icon";
          remove.title = t.removeInterval;
          remove.setAttribute("aria-label", t.removeInterval);
          const trash = document.createElementNS(
            "http://www.w3.org/2000/svg",
            "svg",
          );
          trash.setAttribute("viewBox", "0 0 24 24");
          trash.setAttribute("aria-hidden", "true");
          const path = document.createElementNS(trash.namespaceURI, "path");
          path.setAttribute(
            "d",
            "M9 3h6l1 2h4v2H4V5h4l1-2zm-3 6h12l-1 12H7L6 9zm4 2v8h2v-8h-2zm4 0v8h2v-8h-2z",
          );
          trash.append(path);
          remove.append(trash);
          remove.disabled = this._busy || items.length === 1;
        });
        const add = this._button(t.add, section, () => {
          items.push({
            group,
            source: 0,
            values: {
              hourStart: "",
              hourEnd: "",
              ...(originals[group][0].charge_fv_mode === 1
                ? { power_value: "0" }
                : {}),
            },
          });
          changed();
          redraw();
        });
        add.disabled = this._busy || !originals[group].length;
        const phases = originals[group]
          .map((item) => ({
            item,
            values: Object.entries(item.intensity || {}).filter(
              ([key, value]) => /^(L[123]|l[123])$/.test(key) && value != null,
            ),
          }))
          .filter((item) => item.values.length);
        if (phases.length) {
          const details = node("details", undefined, section);
          node("summary", t.advanced, details);
          phases.forEach(({ item, values }) =>
            node(
              "p",
              `${item.hourStart}–${item.hourEnd}: ${values.map(([key, value]) => `${key}: ${value}`).join(", ")}`,
              details,
            ),
          );
        }
      });
      content.querySelectorAll("button").forEach((button) => {
        button.type = "button";
      });
    };
    redraw();
    actions = node("div", undefined, form);
    actions.className = "form-actions";
    actions.hidden = !create && !this._dirty;
    this._button(t.cancel, actions, () => {
      if (create) dialog.close();
      else if (this._leaveDraft()) {
        this._planning = undefined;
        this._dirty = false;
        this._render();
      }
    }).type = "button";
    save = this._button(create ? t.save : t.changes, actions, () => {});
    save.type = "submit";
    save.className = "primary";
    save.disabled = this._busy || (!create && !this._dirty);
    // All other buttons are ordinary actions, not implicit form submissions.
    form.querySelectorAll("button").forEach((button) => {
      if (button !== save) button.type = "button";
    });
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      if (!form.reportValidity()) return;
      // A changed mode requires an explicit power value, even if the browser
      // filled in a displayed number; the backend enforces this too.
      const payload = {
        action: create ? "create" : "edit",
        entries: entries.flat(),
        confirm_active: selected.profile.active === true,
      };
      if (create) payload.new_name = name.value.trim();
      dialog?.close();
      this._manage(selected, payload);
    });
    if (dialog) {
      dialog.addEventListener("close", () => dialog.remove());
      dialog.showModal();
      name.focus();
    }
  }
  async _manage(selected, payload) {
    if (this._busy) return;
    this._busy = true;
    this._message = "";
    this._render();
    try {
      await this._api("manage", {
        profile_name: selected.profile.name,
        revision: selected.revision,
        ...payload,
      });
      if (payload.action === "create") this._name = payload.new_name;
      this._message = this._t.saved;
      await this._load();
    } catch (error) {
      this._profiles = [];
      this._planning = undefined;
      this._dirty = false;
      this._message = this._t[error.code] || this._t.save_unconfirmed;
    } finally {
      this._busy = false;
      this._render();
    }
  }
  async _save(selected, group, index, allowed) {
    if (this._busy) return;
    this._busy = true;
    this._message = "";
    this._render();
    try {
      await this._api("save_battery", {
        profile_name: selected.profile.name,
        revision: selected.revision,
        group,
        index,
        allowed,
      });
      this._message = this._t.saved;
      await this._load(true);
    } catch (error) {
      this._profiles = [];
      this._planning = undefined;
      this._dirty = false;
      this._message = this._t[error.code] || this._t.save_unconfirmed;
    } finally {
      this._busy = false;
      this._render();
    }
  }
}
customElements.define("v2c-profiles-panel", V2CProfilesPanel);
