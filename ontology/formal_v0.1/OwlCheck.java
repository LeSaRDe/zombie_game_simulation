import java.io.File;
import java.nio.file.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import org.semanticweb.owlapi.apibinding.OWLManager;
import org.semanticweb.owlapi.model.*;
import org.semanticweb.owlapi.profiles.*;
import org.semanticweb.owlapi.reasoner.*;
import org.semanticweb.HermiT.Reasoner;

/** Actual OWLAPI profile checking plus HermiT consistency/class reasoning. */
public class OwlCheck {
  static String q(String s) { return "\""+s.replace("\\","\\\\").replace("\"","\\\"").replace("\n","\\n").replace("\r","\\r").replace("\t","\\t")+"\""; }
  static String arr(Collection<String> xs) { List<String> list=new ArrayList<>(xs); Collections.sort(list); List<String> quoted=new ArrayList<>(); for(String s:list)quoted.add(q(s)); return "["+String.join(",",quoted)+"]"; }
  public static void main(String[] args) throws Exception {
    OWLOntologyManager m=OWLManager.createOWLOntologyManager();
    OWLOntology o=m.loadOntologyFromOntologyDocument(new File(args[0]));
    OWLProfileReport profile=new OWL2DLProfile().checkOntology(o);
    List<String> violations=new ArrayList<>(); for(OWLProfileViolation v:profile.getViolations()) violations.add(v.toString());
    if(!profile.isInProfile()) {
      Files.writeString(Path.of(args[1]),"{\"owl2_dl\":false,\"profile_violations\":"+arr(violations)+"}",StandardCharsets.UTF_8); return;
    }
    OWLReasoner r=new Reasoner.ReasonerFactory().createReasoner(o);
    boolean consistent=r.isConsistent();
    List<String> unsat=new ArrayList<>(),types=new ArrayList<>(),caps=new ArrayList<>(),infectious=new ArrayList<>();
    String z="urn:zombie-game:v0.1:";
    OWLDataFactory df=m.getOWLDataFactory();
    if(consistent) {
      r.precomputeInferences(InferenceType.CLASS_HIERARCHY);
      for(OWLClass c:r.getUnsatisfiableClasses().getEntitiesMinusBottom()) unsat.add(c.getIRI().toString());
      OWLNamedIndividual s=df.getOWLNamedIndividual(IRI.create("urn:zombie-game:example:owl_state"));
      if(o.containsIndividualInSignature(s.getIRI())) {
        for(OWLClass c:r.getTypes(s,false).getFlattened()) types.add(c.getIRI().toString());
        for(OWLNamedIndividual c:r.getObjectPropertyValues(s,df.getOWLObjectProperty(IRI.create(z+"hasCapability"))).getFlattened())caps.add(c.getIRI().toString());
      }
      for(OWLNamedIndividual a:r.getInstances(df.getOWLClass(IRI.create(z+"InfectionCapableActionDefinition")),false).getFlattened())infectious.add(a.getIRI().toString());
    }
    String json="{\"owl2_dl\":true,\"profile_violations\":[],\"consistent\":"+consistent+",\"named_class_count\":"+o.getClassesInSignature().size()+",\"unsatisfiable_classes\":"+arr(unsat)+",\"inferred_types\":"+arr(types)+",\"inferred_capabilities\":"+arr(caps)+",\"infection_capable_actions\":"+arr(infectious)+"}";
    Files.writeString(Path.of(args[1]),json,StandardCharsets.UTF_8);
    r.dispose();
  }
}
