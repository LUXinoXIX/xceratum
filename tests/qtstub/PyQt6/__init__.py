"""Malá náhrada PyQt6 len na testy logiky okna bez grafiky (v prostredí bez Qt).

Neoveruje API Qt – overuje, že naša logika (stavy, signály, toky pripojenia) beží bez chýb.
Widgety si pamätajú text, viditeľnosť a stav; kreslenie sa nevolá; vlákna bežia synchrónne.
"""
