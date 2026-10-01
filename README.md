# Style Lux Auto Details — Landing Page & Agenda Própria

Plataforma Web e Sistema próprio de agendamento (Agenda Própria) para **Style Lux Auto Details** em Aveiro.

> [!IMPORTANT]
> **Estado Atual:** Aplicação a executar localmente em ambiente seguro (`127.0.0.1:8080`). **NÃO está publicada publicamente.**

---

## 🏎️ Sobre o Projeto

O projeto consiste numa Landing Page de alta conversão, desenvolvida sob medida em Português de Portugal, integrada com um motor de agendamento próprio em Python/SQLite sem qualquer dependência de serviços externos (sem Calendly, SimplyBook ou formulários externos).

### Ofertas da Style Lux em Aveiro
- **Lavagem Premium (80 €)**: Lavagem exterior manual, limpeza de jantes, vidros interior/exterior, tablier/laterais, higienização de estofados, revitalização dos plásticos, proteção da pele dos bancos, aspiração com jato de ar, limpeza do ar condicionado, cera protetora e acabamento premium.
- **Lavagem Premium Completa (130 €)**: Todos os serviços do pacote de 80 € **acrescido de Limpeza Técnica de Motor**.

---

## 🚀 Como Iniciar o Servidor Local

1. Navegue para a pasta do projeto:
   ```bash
   cd stylelux-reservas
   ```

2. Inicie o servidor local (Python 3 standard library):
   ```bash
   python3 server.py
   ```

3. Aceda no seu navegador:
   - **Landing Page Pública**: [http://127.0.0.1:8080](http://127.0.0.1:8080)
   - **Painel de Gestão (Admin)**: [http://127.0.0.1:8080/admin](http://127.0.0.1:8080/admin)

---

## 🔐 Autenticação & Ficheiro de Credenciais Privado

As credenciais do painel de administração são geradas automaticamente no primeiro arranque e guardadas exclusivamente num ficheiro privado fora da pasta `public` e fora do Git:

- **Credencial inicial para o dono**: `data/acesso-admin.txt` (Permissões de ficheiro `0600`)
- **Algoritmo de Segurança**: Hashing PBKDF2-HMAC-SHA256 com salt individual de 16 bytes e proteção contra força bruta (bloqueio automático de 15 minutos após 5 tentativas falhadas).

Para consultar o utilizador e a palavra-passe gerados localmente para o seu ambiente de testes:
```bash
cat data/acesso-admin.txt
```

---

## ⚙️ Configuração Provisória da Agenda (Capacidade & Horários)

De acordo com as indicações iniciais do estabelecimento, a agenda encontra-se configurada com os seguintes valores provisórios de arranque:
- **Limite Diário Compartilhado**: 5 lavagens por dia (limite total somando ambas as ofertas).
- **Horários Iniciais de Entrega**: `09:00`, `11:00`, `13:00`, `15:00`, `17:00`.

> [!NOTE]
> Esta configuração é **totalmente editável** pelo administrador através da tab **"Configuração & Vagas"** no painel `/admin` ou via base de dados antes de iniciar a operação pública.

---

## 🧪 Execução dos Testes Automatizados

O projeto inclui uma suite completa de testes de integração e segurança que opera sobre uma base de dados isolada temporária:

```bash
python3 tests/test_backend.py
```

### Validações Testadas
1. Transação atómica contra reservas duplicadas em concorrência.
2. Limite diário de 5 lavagens compartilhado entre serviços.
3. Bloqueio automático de datas passadas e domingos.
4. Preço autoritativo no servidor (80 € / 130 €).
5. Cancelamento de reservas e libertação automática de vaga.
6. Impedimento de reativação de reserva se a vaga tiver sido ocupada.
7. Bloqueio de dia inteiro (`*`).
8. Rejeição de configurações de horários ou limites inválidos.
9. Bloqueio de acesso não autenticado a dados de clientes no endpoint admin.
10. Proteção do servidor contra *Path Traversal* para ficheiros privados (`data/`, `config.py`, etc.).

---

## 🌐 Passos Necessários para Publicação Definitiva (Produção)

Antes de colocar o site em produção para o público geral:

1. **Alojamento & Servidor Persistente**: Configurar um servidor VPS (ex: Ubuntu com Systemd) ou serviço de alojamento que mantenha o processo Python ativo.
2. **Reverse Proxy & HTTPS**: Configurar Nginx ou Caddy com certificado SSL gratuito (Let's Encrypt / Certbot) para acesso seguro via `https://stylelux...`.
3. **Domínio & DNS**: Apontar o registo A do domínio oficial para o endereço IP do servidor.
4. **Cópia de Segurança da BD**: Configurar cronjob de backup periódico do ficheiro `data/stylelux.db`.

## CRM — agenda, clientes e resultados

Abre `/crm` ou `/admin` e entra com a conta privada existente em `data/acesso-admin.txt`. A palavra-passe não mudou. O CRM partilha a mesma base SQLite com o site; não é necessário importar marcações.

- Visão geral com período de datas, valor concluído, recebido e pendente.
- Agenda por dia, semana e mês; fichas, reagendamento, cancelamento e bloqueios.
- Histórico de clientes agrupado por telemóvel, notas e pagamento recebido.
- Gastos em anúncios registados manualmente, editáveis para corrigir valores. Não existe sincronização com Meta Ads nem importação automática de leads Facebook.
- Acordo de comissão e percentagem dos custos por mês, sem percentagens presumidas.
- Comissão apenas sobre marcações atribuídas, concluídas e assinaladas como pagas. Os relatórios usam a data da lavagem; não são contabilidade por data de recebimento. O saldo mostrado é da operação de tráfego (comissão menos a parte dos anúncios), não o lucro da lavadora.
- Exportação CSV do período e filtros atuais; atualização automática de 30 em 30 segundos enquanto não estás a editar.
- Para refletir mudanças no servidor, reinicia `python3 server.py`. Mantém o serviço restrito a `127.0.0.1` enquanto não estiver pronto para produção.

Testes CRM isolados: `python3 tests/test_crm.py`.
