# Règles Maison Cachées — Company A
# ATTENTION : Ces règles n'apparaissent pas dans les règles publiques.
# Elles sont utilisées uniquement pour générer et valider les gold labels.

1. **Règle HR-A1** : Pour les factures STEG supérieures à 1 000,000 TND HTVA, utiliser le code 606100 avec le flag "haute_consommation": true dans les métadonnées gold.
2. **Règle HR-A2** : Les bons de commande informatiques de SysTech Solutions doivent toujours être codifiés en 617000, même si la description mentionne "matériel".
3. **Règle HR-A3** : Les achats Monoprix dont la description contient "entretien" → utiliser 615000 au lieu de 606200.
4. **Règle HR-A4** : Si le timbre fiscal dépasse 1,000 TND, créer une trace d'exception avant validation (needs_review: true).
