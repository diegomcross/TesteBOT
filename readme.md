# Destiny 2 Event Bot para Discord

## Visão Geral

Este bot para Discord foi projetado para ajudar comunidades de Destiny 2 a agendar, gerenciar e participar de eventos como Incursões, Masmorras, Desafios de Osíris, e outras atividades. Ele oferece um sistema de RSVP interativo, criação de eventos via comandos de barra ou DMs, e funcionalidades de administração para configurar o comportamento do bot no servidor.

## Funcionalidades Atuais (Funcionando)

### Criação de Eventos
* **`/agendar`**: Permite criar um novo evento através de um formulário (Modal) diretamente no Discord.
    * Coleta: Nome do Evento, Descrição, Data, Hora.
    * Detecção Automática: Tipo de atividade e número de vagas são inferidos do nome do evento. Se não detectado, o bot pergunta.
    * Seleção de Canal: Ao final, o usuário escolhe em qual canal (previamente configurado) o evento será postado.
* **`/criar_evento`**: Permite criar um novo evento através de um fluxo de perguntas e respostas via Mensagem Direta (DM) com o bot.
    * Fluxo de Perguntas Restaurado: Sequência de perguntas similar à original, incluindo seleção de data por botões e loop de opções adicionais.
    * Suporte a AM/PM: A entrada de hora aceita formatos como "7pm" ou "10am".
    * Detecção Automática: Similar ao `/agendar`.
    * Seleção de Canal: Ao final, o usuário escolhe na DM em qual canal o evento será postado.

### Gerenciamento de Eventos e RSVP
* **Sistema de RSVP Persistente**:
    * Botões ("✅ Vou", "❌ Não Vou", "🔷 Talvez") nas mensagens de evento.
    * Gerencia listas de confirmados, espera, talvez e ausentes.
    * Promoção automática da lista de espera quando vagas são liberadas.
* **Edição de Eventos**:
    * Criadores do evento e usuários com cargos de "gerente de eventos" podem editar eventos.
    * Botão "📝 Editar" na mensagem do evento abre opções para editar:
        * Detalhes básicos (Título, Descrição, Data/Hora) via Modal.
        * Tipo de Atividade e Vagas (via DM).
* **Cancelamento de Eventos**:
    * Criadores e gerentes podem cancelar eventos através do botão "🗑️ Apagar".
    * A mensagem do evento é atualizada para "[CANCELADO]" e agendada para deleção.
* **`/lista`**: Exibe os eventos agendados para os próximos 3 dias no canal onde o comando foi executado (resposta efêmera).
* **`/gerenciar_rsvp`**: Permite que criadores/gerentes modifiquem manualmente o status de RSVP de um usuário para um evento.

### Cargos Temporários por Evento
* **Criação Automática**: Um cargo temporário é criado automaticamente quando um evento é criado (via `/agendar` ou `/criar_evento`).
    * Nome do cargo: `Evento: {Título Curto} - {DD/MM}`.
    * ID do cargo é salvo no banco de dados junto ao evento.
* **Gerenciamento de Membros**:
    * Usuários que respondem "Vou" ou são colocados na "Lista de Espera" são adicionados automaticamente ao cargo.
    * Usuários que removem seu RSVP ou mudam para "Não Vou"/"Talvez" são removidos do cargo.
* **Deleção Automática**:
    * O cargo é deletado quando o evento é marcado como "CONCLUÍDO" pela tarefa de limpeza.
    * O cargo é deletado quando o evento é "CANCELADO" manualmente.
* **Renomeação Automática**: Se o título ou a data do evento são editados, o nome do cargo temporário é atualizado.
* **Notificações**: Se a data/hora do evento é alterada, uma mensagem mencionando o cargo temporário é enviada no canal do evento.

### Configuração e Administração
* **`/configurar_canal_eventos <#canal>`**:
    * Designa um canal específico para receber as postagens de eventos.
    * Configura as permissões do canal para que apenas o bot possa enviar mensagens, tornando-o um canal de "anúncios de eventos".
* **`/remover_canal_evento_cfg <#canal>`**: Remove um canal da lista de canais designados para postagem.
* **`/definir_canal_lista <#canal>`**: Define um canal para receber o resumo diário de eventos. Este canal também pode ser o canal "principal" para uso de comandos.
* **`/definir_cargos_gerente [@cargo1] ...`**: Define quais cargos têm permissão para gerenciar todos os eventos (editar, apagar, usar `/gerenciar_rsvp`).
* **`/definir_cargos_restritos_padrao [@cargo1] ...`**: Define cargos que, por padrão, não poderão interagir com o sistema de RSVP dos eventos.

### Tarefas Agendadas (Background)
* **Lembretes de Evento**: Envia lembretes (mencionando o cargo temporário no canal do evento ou, como fallback, via DM para participantes "Vou") ~15 minutos antes do início do evento.
* **Limpeza de Eventos Concluídos**: Marca eventos como "[CONCLUÍDO]" automaticamente após um período (ex: 4 horas após o término), deleta o cargo temporário associado e agenda a mensagem do evento para deleção futura.
* **Deleção de Mensagens**: Apaga as mensagens de eventos cancelados ou concluídos após um período configurado (ex: 1 hora para cancelados, 24 horas para concluídos).
* **Resumo Diário de Eventos**: Posta uma lista dos próximos eventos no canal configurado via `/definir_canal_lista`.

### Geral
* **Banco de Dados**: Utiliza SQLite para persistência de dados (eventos, RSVPs, configurações).
* **Estrutura Modular**: Código organizado em Cogs (`event_cog`, `scheduling_cog`, `admin_cog`, `tasks_cog`, `listeners_cog`) e arquivos de utilidade (`utils.py`, `database.py`, `role_utils.py`, `constants.py`).
* **Tratamento de Erros**: Handlers básicos para erros de comando.

## Configuração Inicial do Bot (Resumo)

1.  **Ambiente Python**: Certifique-se de ter Python 3.10 ou superior.
2.  **Bibliotecas**: Instale as dependências (ex: `discord.py`, `pytz`, `dateparser`, `python-dotenv`)
    ```bash
    pip install -r requirements.txt 
    ```
    (Crie um arquivo `requirements.txt` se ainda não tiver).
3.  **Token do Bot**: Configure o token do seu bot no arquivo `config.py` (ou através de variáveis de ambiente/segredos se estiver usando Replit/Docker).
    ```python
    # config.py
    TOKEN = "SEU_TOKEN_AQUI"
    GUILD_ID = SEU_GUILD_ID_OPCIONAL # Para sincronização rápida de comandos em um servidor de teste
    ```
4.  **Primeira Execução**: Ao iniciar o bot pela primeira vez, o arquivo de banco de dados (`destiny_events.db`) será criado.
5.  **Comandos de Configuração no Discord (como admin):**
    * `/definir_canal_lista`: Para o resumo diário.
    * `/configurar_canal_eventos`: Para cada canal onde você quer que os eventos sejam postados.
    * `/definir_cargos_gerente` (opcional): Para dar permissão de gerenciamento a outros cargos.
    * `/definir_cargos_restritos_padrao` (opcional): Para restringir RSVPs para certos cargos.

## Planos Futuros / Funcionalidades Pendentes

* **Eventos Recorrentes**:
    * Interface para o usuário definir regras de recorrência (diária, semanal, mensal, com data de término ou número de ocorrências).
    * Tarefa agendada para gerar as "instâncias" dos eventos recorrentes.
    * Modificações no banco de dados para armazenar as regras de recorrência.
* **Edição Detalhada de Cargos no Evento**:
    * Ativar e implementar a lógica para os botões "Mencionar Cargos" e "Restringir Cargos" na `EditOptionsView` para permitir a edição desses campos após a criação do evento.
* **Validação Robusta de Cargos na DM**: Melhorar a busca Qe validação de cargos ao adicioná-los para menção ou restrição durante a criação de evento via `/criar_evento` na DM (atualmente a validação é mais simples nesse fluxo).

## Estrutura de Arquivos Principal

```
/
├── main.py                 # Ponto de entrada, carrega cogs
├── config.py               # Configurações (TOKEN, GUILD_ID)
├── database.py             # Lógica de interação com o banco de dados SQLite
├── utils.py                # Funções utilitárias gerais e Views de UI compartilhadas
├── role_utils.py           # Funções utilitárias para gerenciamento de cargos temporários
├── constants.py            # Constantes globais (fuso horário, listas de atividades, etc.)
└── cogs/
    ├── admin_cog.py        # Comandos de administração do servidor para o bot
    ├── event_cog.py        # Comando /criar_evento, Views de RSVP/edição, lógica de evento
    ├── scheduling_cog.py   # Comando /agendar com Modal
    ├── tasks_cog.py        # Tarefas agendadas (lembretes, cleanup, digest)
    └── listeners_cog.py    # Listeners de eventos globais (on_ready, on_error)
```

---

Este `README.md` deve cobrir bem o estado atual e os planos. Você pode salvá-lo na raiz do seu projeto.
