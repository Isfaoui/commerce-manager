# Guide d'utilisation - Commerce Manager

Ce guide explique comment utiliser l'application, ecran par ecran. Les
noms utilises ici (boutons, onglets) correspondent exactement a ce que
vous voyez dans l'application.

---

## 1. Premier lancement

### Installer (une seule fois)
1. Installez Python depuis python.org (cochez **"Add Python to PATH"**).
2. Double-cliquez sur `install.bat`.

### Lancer l'application (a chaque utilisation)
Double-cliquez sur `run.bat`. Une fenetre s'ouvre - c'est l'application,
pas un navigateur.

### Choisir le type de commerce
A la toute premiere ouverture, un ecran vous demande de choisir :
**Restaurant**, **Cafe**, **Epicerie / Commerce de detail**, **Service**,
ou **Autre**.

**Ce choix est definitif** - il ne pourra plus etre change apres. Il
determine :
- Les types de commande disponibles en caisse (Sur place / A emporter /
  Livraison, ou une seule option pour Epicerie/Service)
- Si l'onglet "Tables" et l'option "Recette" apparaissent dans Gestion
- Les categories de produits creees automatiquement au depart

Reflechissez avant de valider. Si vous hesitez entre deux types, "Autre"
garde toutes les options disponibles.

---

## 2. La navigation

Cinq onglets en haut de l'ecran : **Accueil**, **Caisse**, **Gestion**,
**Personnel**, **Parametres**. On peut naviguer entre eux a tout moment,
meme en pleine vente.

---

## 3. Accueil

La vue d'ensemble de la journee :
- Chiffre d'affaires et nombre de ventes du jour
- Un graphique des ventes des 7 derniers jours
- Un graphique des meilleures ventes
- Commandes actuellement ouvertes (non payees)
- Transactions recentes
- Alertes de stock faible
- Qui est actuellement en service (pointe present)

Rien a configurer ici - c'est purement une vue de suivi.

---

## 4. Caisse (l'ecran principal, celui que vous utiliserez le plus)

### Etape 1 : choisir le type de commande
En haut : **A emporter**, **Sur place**, **Livraison** (les options
disponibles dependent du type de commerce choisi au depart).

Si **Sur place** : une liste de tables apparait. Vous devez selectionner
une table avant de pouvoir continuer. **Si aucune table n'apparait**,
c'est normal a l'installation - allez dans Gestion → Tables pour en
ajouter (voir section 5).

### Etape 2 : ajouter des produits au ticket
Trois facons :
- **Cliquer sur un produit** dans la grille
- **Rechercher** par nom dans la barre de recherche
- **Scanner un code-barres** (ou le taper puis Entree) dans le champ en
  haut a droite - fonctionne avec n'importe quel scanner USB/Bluetooth,
  aucune configuration necessaire

Pour une vente ponctuelle qui ne merite pas une fiche produit
permanente (un pourboire, un service specifique) : bouton
**+ Article libre**.

Chaque produit du ticket peut voir sa quantite ajustee avec les boutons
**-** et **+**.

### Etape 3 : envoyer la commande
Bouton **Envoyer la commande**. Cela cree une commande "ouverte" et
reserve le stock immediatement. La commande apparait dans le panneau
**Commandes ouvertes** a droite.

### Etape 4 : encaisser
Sur une commande ouverte, bouton **Encaisser** : choisissez le mode de
paiement (Especes, Carte manuel, ou Carte via TPE - simule pour
l'instant, voir README.md pour brancher un vrai terminal). Le paiement
cree automatiquement un recu (sauf si les recus sont desactives dans
Parametres).

Le ticket affiche toujours Sous-total (HT), TVA, et Total - vos prix
sont TTC (taxe deja incluse), le client paie toujours le meme montant,
c'est juste la decomposition qui s'affiche.

### Marquer comme servi
Chaque commande (Sur place, A emporter, Livraison) a un statut "Servi"
independant du paiement - une commande a emporter payee d'avance reste
visible dans **Commandes en cours** jusqu'a ce qu'elle soit marquee
**Servi**, meme si elle est deja payee.

### Remise
Champ "Remise" au-dessus du total : pourcentage ou montant fixe en MAD.
S'applique avant le calcul de la TVA, donc le client paie bien le
montant reduit affiche.

### Mettre en attente
Si vous etes interrompu en pleine vente, bouton **Mettre en attente** :
le ticket en cours est sauvegarde sans creer de commande reelle (aucun
stock touche). Il apparait dans le panneau **En attente** avec un
bouton **Reprendre** pour continuer plus tard, ou **Suppr.** pour
l'abandonner.

### Diviser l'addition
Sur une commande ouverte avec plusieurs articles, bouton **Diviser** :
assignez chaque article a un groupe (bouton "Groupe 1" / "Groupe 2" sur
chaque ligne), puis confirmez. Deux commandes separees sont creees,
chacune payable independamment.

### Annuler ou rembourser
Bouton **Annuler** sur n'importe quelle commande (ouverte ou deja
payee). **Une autorisation est toujours obligatoire** - impossible de
l'ignorer :
- Choisissez la methode : Code PIN, Carte NFC, Mot de passe, ou
  Approbation manager
- Selectionnez le manager/responsable
- Entrez le motif (obligatoire)

Seuls les employes avec un role **Owner** ou **Manager** peuvent
approuver - un **Cashier** ne peut pas. Toute annulation/remboursement
est enregistre dans Parametres → Journal de securite, avec qui l'a
demande, qui l'a approuve, et pourquoi.

### Le recu
S'affiche automatiquement apres paiement (si active). Bouton
**Imprimer** dedans pour lancer l'impression. On peut le retrouver et le
reimprimer plus tard dans Gestion → Ventes.

---

## 5. Gestion

Cinq (ou six) sous-onglets selon votre type de commerce.

### Inventaire
**Ajouter un produit** : deux types possibles.
- **Simple (achat/revente)** : vous achetez et revendez tel quel (eau,
  soda). Renseignez cout, prix de vente, stock, unite.
- **Recette (fabrique)** *(Restaurant/Cafe/Autre seulement)* : fabrique
  a partir d'ingredients (un cafe = grains + lait). Pas de cout ni de
  stock a saisir directement - juste le prix de vente et la liste des
  ingredients avec leurs quantites. Le cout et la disponibilite sont
  calcules automatiquement.

Pour une matiere premiere qui ne se vend jamais directement (grains de
cafe, lait) : decochez **"Vendable directement en caisse"** en creant
le produit "Simple" correspondant.

Vous pouvez ajouter une **photo** a chaque produit (PNG/JPG/WEBP/GIF,
5MB max) - elle apparait en miniature ici et sur la tuile du produit en
caisse.

Chaque produit de la liste a deux boutons :
- **Modifier** : recharge le produit dans le formulaire pour le
  modifier (le type Simple/Recette ne peut plus changer une fois cree)
- **Supprimer** : le retire de la caisse (l'historique des ventes
  passees reste intact). Impossible de supprimer une matiere premiere
  encore utilisee dans une recette active.

### Fournisseurs
Ajoutez vos fournisseurs (nom, telephone, email). Utilises lors des
receptions de stock.

### Achats
**Nouvelle reception** : selectionnez un fournisseur (optionnel), un
produit, une quantite et un cout unitaire, puis **Ajouter la ligne**.
Repetez pour plusieurs produits, puis **Enregistrer la reception** - le
stock et le cout du produit sont mis a jour immediatement.

Chaque achat dans l'historique a un bouton **Supprimer** : annule
l'achat et retire le stock correspondant (le cout du produit n'est pas
annule s'il a change depuis).

### Tables *(Restaurant/Cafe/Autre seulement)*
**Obligatoire pour que "Sur place" fonctionne en caisse.** Ajoutez
chaque table avec un nom et un nombre de places.

### Ventes
Historique complet des ventes, avec un bouton **Imprimer** sur chacune
pour reimprimer un recu a tout moment, et **Exporter en CSV** pour
telecharger tout l'historique.

### Rapports
Chiffre d'affaires, cout des marchandises, marge, TVA collectee, ventes
des 7 derniers jours, meilleures ventes. **Exporter en CSV** pour un
fichier telechargeable, **Imprimer / Exporter en PDF** pour ouvrir la
boite de dialogue d'impression - choisissez "Enregistrer en PDF"
(disponible sur Windows/Mac) pour obtenir un fichier PDF.

---

## 6. Personnel

**Ajouter un employe** : nom, email, role (Owner / Manager / Cashier -
crees automatiquement des le premier lancement), code PIN (sert a
approuver les annulations en caisse), mot de passe, taux horaire
optionnel.

La liste des employes affiche qui est actuellement **en service**, avec
un bouton pour **pointer l'entree/la sortie**.

Rappel des roles :
- **Owner / Manager** : peuvent approuver les annulations/remboursements
- **Cashier** : ne peut pas - doit demander a un manager

---

## 6bis. Clients

Optionnel - les ventes fonctionnent normalement sans aucun client.
Utile surtout pour le **credit client (ardoise)** : un client regulier
peut prendre des articles maintenant et payer plus tard.

**Ajouter un client** : nom, telephone, email, adresse (tout optionnel
sauf le nom).

**Utiliser le credit en caisse** : au moment d'encaisser, choisissez le
client dans le menu deroulant, puis le mode de paiement "Credit client"
(cree par defaut). Le solde du client augmente du montant de la vente -
la vente elle-meme est enregistree normalement.

**Regler un solde** : bouton **Gerer** sur un client, puis "Enregistrer
le paiement" avec le montant recu. Le solde diminue d'autant.

Un client avec un solde non nul ne peut pas etre supprime - reglez le
solde d'abord.

---

## 7. Parametres

### Apparence
Mode Clair/Sombre/Automatique, et une couleur principale (votre couleur
de marque). S'applique instantanement, sans redemarrer.

### Informations du commerce
Nom, devise, taux de TVA par defaut. Le type de commerce est affiche
mais non modifiable (voir section 1).

### Ticket de caisse
- Case a cocher pour **activer/desactiver les recus** - si desactive,
  rien ne s'affiche automatiquement apres un paiement (l'historique
  reste consultable dans Gestion → Ventes)
- Adresse, telephone, message de remerciement personnalisables
- **Apercu en direct** juste en dessous, mis a jour a chaque frappe

### Modes de paiement
Ajoutez vos modes de paiement (Especes, Carte, etc.), avec une case
"Via TPE" pour ceux qui passent par un terminal de paiement, et une
case "Credit client" pour ceux qui doivent alimenter le solde credit
d'un client (voir section 6bis) plutot que d'etre comptes comme recus
immediatement.

### Sauvegarde et restauration
Une sauvegarde automatique est creee chaque jour (les 5 dernieres sont
gardees). Bouton pour en creer une manuellement a tout moment. Chaque
sauvegarde inclut la base de donnees ET les photos de produits.
**Telechargez vos sauvegardes de temps en temps** vers une cle USB ou
un dossier cloud - une sauvegarde qui reste uniquement sur cet
ordinateur ne protege pas contre une panne de cet ordinateur.
**Restaurer** remplace toutes les donnees actuelles - action
irreversible, redemarrez l'application juste apres.

### Journal de securite
Liste complete de toutes les annulations et remboursements : qui,
quand, approuve par qui, comment, et pourquoi. Rien n'y echappe.

---

## 8. Checklist avant votre premiere vraie journee

1. [ ] Type de commerce choisi (definitif - section 1)
2. [ ] Vos vrais employes ajoutes dans Personnel, avec leurs codes PIN
3. [ ] Vos vraies categories et produits crees dans Gestion → Inventaire
      (pas les produits de demonstration)
4. [ ] Si Restaurant/Cafe : vos tables ajoutees dans Gestion → Tables
5. [ ] Si vous avez des produits "recette" (cafe, plats prepares) :
      leurs ingredients crees comme produits "Simple" d'abord
6. [ ] Modes de paiement configures dans Parametres
7. [ ] Informations du commerce et ticket de caisse personnalises dans
      Parametres

Une fois cette liste terminee, l'application est prete pour une
utilisation reelle.
