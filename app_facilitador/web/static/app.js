// Acompanha o que roda em segundo plano: a varredura e a conexão com o
// Outlook.
//
// As duas levam minutos e acontecem numa thread do servidor, então a tela
// consulta o andamento periodicamente. A página só é recarregada na
// transição de "rodando" para "parado" — recarregar a cada consulta
// atrapalharia quem está preenchendo um formulário.

const INTERVALO_MS = 2000;

const elementoStatus = document.getElementById("status-varredura");
const elementoResumo = document.getElementById("resumo-varredura");
const barraVarredura = document.getElementById("barra-varredura");
const botaoVarrer = document.getElementById("botao-varrer");
const formParar = document.getElementById("form-parar");
const botaoParar = document.getElementById("botao-parar");

const avisoLogin = document.getElementById("aviso-login");
const avisoAndamento = document.getElementById("aviso-login-andamento");
const mensagemLogin = document.getElementById("mensagem-login");
const formJaEntrei = document.getElementById("form-ja-entrei");
const botaoLogin = document.getElementById("botao-login");
const pilulaConexao = document.getElementById("pilula-conexao");
const textoConexao = document.getElementById("texto-conexao");

let varreduraRodava = false;
let loginRodava = false;

// Começa com o que o servidor já renderizou, para o botão de varrer não
// piscar de habilitado para desabilitado na primeira consulta.
let conectado = document.body.dataset.conectado === "sim";

function descreverVarredura(estado) {
  if (estado.running) {
    if (estado.stopping) {
      return "parando… (terminando o passo atual)";
    }
    const pasta = estado.folder || "Caixa de Entrada";
    return `varrendo ${pasta} — ${estado.scanned} e-mails percorridos`;
  }
  if (estado.error) {
    return "a última varredura falhou";
  }
  if (estado.finished_at) {
    return `última varredura terminou às ${estado.finished_at}`;
  }
  return "nenhuma varredura nesta sessão";
}

function mostrarResumo(estado) {
  const temErro = Boolean(estado.error);
  const temResumo = estado.summary && estado.summary.length > 0;

  elementoResumo.classList.toggle("resumo-erro", temErro);
  elementoResumo.classList.toggle("oculto", !temErro && !temResumo);

  if (temErro) {
    elementoResumo.textContent = estado.error;
  } else if (temResumo) {
    elementoResumo.textContent = estado.summary.join("\n");
  }
}

async function consultar(caminho) {
  const resposta = await fetch(caminho);
  return resposta.json();
}

async function atualizarVarredura() {
  let estado;
  try {
    estado = await consultar("/varredura/status");
  } catch {
    elementoStatus.textContent = "servidor fora do ar";
    return;
  }

  elementoStatus.textContent = descreverVarredura(estado);
  elementoStatus.classList.toggle("status-rodando", estado.running);
  barraVarredura.classList.toggle("oculto", !estado.running);

  // Sem acesso ao Outlook a varredura só pode falhar; melhor não deixar
  // clicar do que devolver um erro previsível.
  botaoVarrer.disabled = estado.running || !conectado;
  botaoVarrer.title = conectado ? "" : "Conecte o app ao Outlook primeiro";
  botaoVarrer.textContent = estado.running ? "Varrendo…" : "Varrer agora";

  // O botão de parar só existe enquanto há o que parar. Depois de clicado,
  // fica desabilitado e vira "Parando…" — o pedido já foi enviado, clicar
  // de novo não adianta.
  formParar.classList.toggle("oculto", !estado.running);
  botaoParar.disabled = estado.stopping;
  botaoParar.textContent = estado.stopping ? "Parando…" : "Parar varredura";

  mostrarResumo(estado);

  if (varreduraRodava && !estado.running) {
    window.location.reload();
  }
  varreduraRodava = estado.running;
}

function marcarConectado(conectado) {
  pilulaConexao.classList.toggle("pilula-ok", conectado);
  pilulaConexao.classList.toggle("pilula-alerta", !conectado);
  textoConexao.textContent = conectado ? "Outlook conectado" : "Outlook desconectado";
}

async function atualizarLogin() {
  let estado;
  try {
    estado = await consultar("/login/status");
  } catch {
    return;
  }

  conectado = estado.connected;
  marcarConectado(conectado);

  if (botaoLogin) {
    botaoLogin.disabled = estado.running;
    botaoLogin.textContent = estado.running ? "Aguardando login…" : "Conectar ao Outlook";
  }

  const textoAndamento = estado.error || estado.message;
  const mostrar = Boolean(textoAndamento) && (estado.running || estado.error);

  avisoAndamento.classList.toggle("oculto", !mostrar);
  avisoAndamento.classList.toggle("aviso-erro", Boolean(estado.error));
  if (mostrar) {
    mensagemLogin.textContent = textoAndamento;
  }

  // A saída manual só faz sentido enquanto a espera está de pé.
  formJaEntrei.classList.toggle("oculto", !estado.running);

  // Conectar muda a tela inteira: o aviso some e a varredura passa a
  // funcionar. Recarregar é o jeito mais simples de refletir isso.
  if (loginRodava && !estado.running && estado.connected) {
    window.location.reload();
  }
  loginRodava = estado.running;

  if (avisoLogin && estado.connected && !estado.running) {
    avisoLogin.classList.add("oculto");
  }
}

let reunioesRodava = false;

async function atualizarReunioes() {
  const aviso = document.getElementById("status-reunioes");
  if (!aviso) return;

  let estado;
  try {
    estado = await consultar("/reunioes/status");
  } catch {
    return;
  }

  const texto = estado.running ? "lendo o calendário…" : estado.error;
  aviso.textContent = texto || "";
  aviso.classList.toggle("oculto", !texto);
  aviso.classList.toggle("erro-inline", Boolean(estado.error));

  if (reunioesRodava && !estado.running && !estado.error) {
    window.location.reload();
  }
  reunioesRodava = estado.running;
}

async function atualizar() {
  await Promise.all([atualizarVarredura(), atualizarLogin(), atualizarReunioes()]);
}

atualizar();
setInterval(atualizar, INTERVALO_MS);
