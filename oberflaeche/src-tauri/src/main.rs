// Kein Konsolenfenster in der gebauten Fassung.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    // Allererste Anweisung, vor jedem Faden: 'RUNASADMIN' darf nicht an den
    // Dienst vererbt werden (siehe kompat.rs).
    let kompat = vermerk_lib::kompat::bereinigen();
    vermerk_lib::run(kompat);
}
