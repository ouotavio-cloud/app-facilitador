// Acompanha a varredura em andamento.
//
// A varredura leva minutos, então roda em segundo plano no servidor e a
// tela consulta o andamento periodicamente. Quando termina, a página é
// recarregada uma vez para trazer os resultados novos.

const INTERVALO_MS = 2000;

const elementoStatus = document.getElementById("status-varredura");
const elementoResumo = document.getElementById("resumo-varredura");
const botaoVarrer = document.getElementById("botao-varrer");

let estavaRodando = false;

function descreverEstado(estado) {
  if (estado.running) {
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
  if (estado.error) {
    elementoResumo.textContent = `Erro: ${estado.error}`;
    elementoResumo.classList.remove("oculto");
    return;
  }
  if (estado.summary && estado.summary.length > 0) {
    elementoResumo.textContent = estado.summary.join("\n");
    elementoResumo.classList.remove("oculto");
    return;
  }
  elementoResumo.classList.add("oculto");
}

async function atualizarStatus() {
  let estado;
  try {
    const resposta = await fetch("/varredura/status");
    estado = await resposta.json();
  } catch {
    elementoStatus.textContent = "servidor fora do ar";
    return;
  }

  elementoStatus.textContent = descreverEstado(estado);
  elementoStatus.classList.toggle("status-rodando", estado.running);
  botaoVarrer.disabled = estado.running;
  botaoVarrer.textContent = estado.running ? "Varrendo…" : "Varrer agora";

  mostrarResumo(estado);

  // Recarrega só na transição de rodando para parado: é quando há
  // resultados novos para mostrar nas tabelas. Recarregar a cada consulta
  // atrapalharia quem está preenchendo um formulário.
  if (estavaRodando && !estado.running) {
    window.location.reload();
  }
  estavaRodando = estado.running;
}

atualizarStatus();
setInterval(atualizarStatus, INTERVALO_MS);
