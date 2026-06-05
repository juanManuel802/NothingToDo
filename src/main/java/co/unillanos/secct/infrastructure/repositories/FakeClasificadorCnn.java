package co.unillanos.secct.infrastructure.repositories;

import co.unillanos.secct.entities.PartePez;
import co.unillanos.secct.usecases.dto.ResultadoClasificacion;
import co.unillanos.secct.usecases.ports.ClasificadorCnnPort;

import java.util.List;

public class FakeClasificadorCnn implements ClasificadorCnnPort {

    private final int categoriaNtc;
    private final double puntajeConfianza;

    public FakeClasificadorCnn() {
        this(3, 0.90);
    }

    public FakeClasificadorCnn(int categoriaNtc, double puntajeConfianza) {
        this.categoriaNtc = categoriaNtc;
        this.puntajeConfianza = puntajeConfianza;
    }

    @Override
    public List<ResultadoClasificacion> clasificar(byte[] imagen) {
        return List.of(new ResultadoClasificacion(PartePez.OJO, categoriaNtc, puntajeConfianza));
    }
}
