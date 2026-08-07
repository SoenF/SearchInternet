# LeadBridge for Make — c'est quoi, en clair

## Le problème de départ

Quand une entreprise récupère des prospects ("leads") via les formulaires
Facebook Lead Ads, elle utilise souvent Make.com pour transférer
automatiquement chaque prospect vers un CRM (Airtable, Outlook, Gmail...).

Deux bugs réels, trouvés sur le forum officiel de Make (deux vraies
discussions, pas des suppositions), cassent régulièrement cette
automatisation :

1. **Un bug de permission côté Facebook** : la récupération du prospect
   échoue avec une erreur cryptique (`GraphMethodException 100`), même quand
   tout est configuré correctement selon l'interface de Meta. La vraie cause
   probable (que Meta n'affiche jamais) : le token d'accès n'a pas
   exactement la bonne permission, ou a été créé par quelqu'un qui n'a pas
   le bon rôle sur le compte publicitaire.
2. **Plusieurs formulaires sur une même page Facebook cassent Make** :
   chaque formulaire a des questions différentes, donc des noms de champs
   différents. Make ne sait gérer ça que si on duplique le scénario pour
   chaque formulaire — sinon les données arrivent vides.

## Ce que fait notre produit

Un petit service (le code qu'on construit) qui se place **entre Facebook et
Make** :
- Il récupère le prospect de façon fiable, avec un diagnostic clair si ça
  échoue (au lieu de l'erreur cryptique de Facebook).
- Il "normalise" les champs de n'importe quel formulaire vers un format
  **toujours identique**. Make n'a donc plus besoin que d'**un seul**
  scénario, quel que soit le formulaire d'où vient le prospect.

## Les deux façons de le vendre

**1. Vente unique (one-time)** — quelqu'un achète le **code source** une
fois (ex. 129 $), l'héberge lui-même (son propre Render, ses propres
identifiants Facebook/Make), et ne paie plus jamais. Simple, mais ça ne
génère pas de revenu récurrent.

**2. Abonnement hébergé (subscription)** — au lieu de vendre le code, *toi*
tu héberges le service, et des clients s'abonnent chaque mois (ex.
29-49 $/mois). Ils ne touchent jamais au code : ils remplissent un petit
formulaire avec les infos de leur page Facebook, et ton service traite
leurs prospects pour eux. Ça génère du MRR (revenu récurrent) — ce qui
correspond mieux à l'objectif de bâtir un portefeuille de petits SaaS
revendables plus tard.

## Comment le même code fait les deux, sur un seul serveur Render

- Un client "achat unique" paie via Stripe → reçoit un email avec un lien
  pour télécharger le code source.
- Un client "abonnement" paie via Stripe → reçoit un email avec un lien vers
  un petit formulaire où il indique les infos de sa page Facebook → le
  service commence à traiter ses prospects automatiquement.
- Quand un prospect Facebook arrive, le service regarde d'abord s'il
  appartient à un client abonné (table `tenants`) ; sinon, il utilise la
  configuration globale (cas de l'achat unique auto-hébergé).

## Le point important à ne pas oublier

Pour **vraiment** vendre l'abonnement hébergé à d'autres entreprises (lire
les pages Facebook d'*autres* personnes que toi), Facebook exige une
validation officielle de ton application ("App Review", "Advanced Access").
Ce n'est **pas automatique**, ça peut prendre du temps, et ce n'est pas
garanti. Sans ça, Facebook ne laisse lire que **tes propres pages** — pas
celles de futurs clients. C'est un vrai obstacle administratif chez Meta,
pas un problème de code.
