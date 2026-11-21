// Runs before first paint (classic script): apply the saved theme so there is no white flash.
document.documentElement.dataset.theme = localStorage.getItem("spaghetti.theme") || "dark";
