Firemné súbory pre inštaláciu Firemnej VPN
==========================================

Tento priečinok „firma“ dajte vedľa súboru FiremnaVPN-x.y.z.pkg (napr. na USB alebo
zdieľaný disk). Inštalátor si z neho sám vezme:

  firma/FiremnaVPN.ini      nastavenia správcu (pripojenia, vydavatelia certifikátov, ...)
  firma/profily/*.xml       XML profily Cisca (napr. firma.xml)
  firma/ca/*.crt            certifikáty firemnej certifikačnej autority (koreňová aj sprostredkujúca)

Osobné certifikáty sem nepatria – každý používateľ si svoj vymení v aplikácii
(Vymeniť certifikát…), keď mu ho pošle IT oddelenie.

Tieto súbory nikdy nedávajte do verejného repozitára na GitHub.
